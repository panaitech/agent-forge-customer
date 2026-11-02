# 职责：WeCom Bridge HTTP 入口——企微回调验签解密、确认深链兑换、健康检查。
"""雨中情企微对接服务。"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from app.config import Settings, get_settings
from app.crypto import wecom_crypt as crypt
from app.forge.client import ForgeClient
from app.identity.service import IdentityService
from app.identity.store import IdentityStore
from app.messages import templates as msg
from app.pipeline.inbound import InboundPipeline, TaskStore
from app.ticket import token as ticket_mod
from app.wecom.client import WeComClient
from app.wecom.xmlutil import parse_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("bridge")


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = IdentityStore(settings.identity_db())
        identity = IdentityService(settings, store)
        wecom = WeComClient(settings)
        forge = ForgeClient(settings)
        tasks = TaskStore(settings.data_dir / "inbound_task.sqlite3")
        pipeline = InboundPipeline(settings, identity, wecom, forge, tasks)
        app.state.settings = settings
        app.state.identity = identity
        app.state.wecom = wecom
        app.state.pipeline = pipeline
        log.info(
            "bridge ready corp_configured=%s tenant_configured=%s dry_forge=%s auto_provision=%s",
            bool(settings.wecom_corp_id),
            bool(settings.af_tenant_id),
            settings.dry_run_forge,
            settings.identity_auto_provision,
        )
        yield

    app = FastAPI(title="Yuzq WeCom Bridge", version="0.1.1", lifespan=lifespan)

    async def safe_handle(message) -> None:
        try:
            await app.state.pipeline.handle(message)
        except Exception:
            log.exception("inbound pipeline crashed userid=%s", getattr(message, "userid", "?"))
            try:
                await app.state.wecom.send_text(
                    message.userid,
                    msg.failed("-", "处理异常，请稍后重试或联系管理员"),
                )
            except Exception:
                log.exception("failure notify failed")

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/wecom/callback")
    async def callback_verify(
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
        echostr: str = Query(...),
    ):
        """企微配置回调 URL 时的 GET 校验。"""
        if not crypt.verify_signature(
            settings.wecom_token, timestamp, nonce, echostr, msg_signature
        ):
            raise HTTPException(status_code=403, detail="bad signature")
        try:
            plain = crypt.decrypt(
                settings.wecom_encoding_aes_key,
                echostr,
                expect_corp_id=settings.wecom_corp_id or None,
            )
        except crypt.CryptError as err:
            raise HTTPException(status_code=403, detail="decrypt failed") from err
        return PlainTextResponse(plain)

    @app.post("/wecom/callback")
    async def callback_receive(request: Request, background: BackgroundTasks):
        """接收加密消息；验签失败直接拒绝；业务异步处理以满足回调时限。"""
        params = request.query_params
        msg_signature = params.get("msg_signature", "")
        timestamp = params.get("timestamp", "")
        nonce = params.get("nonce", "")
        body = (await request.body()).decode("utf-8")

        try:
            encrypt = crypt.extract_encrypt_from_xml(body)
        except crypt.CryptError:
            raise HTTPException(status_code=400, detail="bad body")

        if not crypt.verify_signature(
            settings.wecom_token, timestamp, nonce, encrypt, msg_signature
        ):
            raise HTTPException(status_code=403, detail="bad signature")

        try:
            plain = crypt.decrypt(
                settings.wecom_encoding_aes_key,
                encrypt,
                expect_corp_id=settings.wecom_corp_id or None,
            )
        except crypt.CryptError as err:
            raise HTTPException(status_code=403, detail="decrypt failed") from err

        message = parse_message(plain, fallback_corp_id=settings.wecom_corp_id)
        if not message.userid:
            return PlainTextResponse("success")

        if message.msg_type in {"text", "file", "image"}:
            background.add_task(safe_handle, message)

        return PlainTextResponse("success")

    @app.get("/confirm")
    async def confirm(ticket: str = Query(...)):
        """兑换短时 ticket，跳转到协作运行页或审批页（演示级，非 SSO；生产需企微 OAuth）。"""
        try:
            payload = ticket_mod.verify(settings, ticket)
        except ticket_mod.TicketError:
            return HTMLResponse(
                "<h3>确认链接无效或已过期</h3><p>请返回企业微信合同助手会话，重新获取「去确认」链接。</p>",
                status_code=400,
            )
        base = settings.af_console_base_url.rstrip("/")
        q = urlencode({"owner": payload.owner_id, "tenant": payload.tenant_id})
        # 优先打开协作运行详情（含 HITL）；无 run 时落到审批列表
        if payload.run_id:
            target = f"{base}/teams/runs/{payload.run_id}?{q}"
        else:
            target = f"{base}/approvals?{q}"
        return RedirectResponse(target, status_code=302)

    @app.post("/admin/import-members")
    async def import_members(request: Request):
        """过渡导入；须配置 BRIDGE_ADMIN_TOKEN，并携带头 X-Bridge-Admin-Token。"""
        expected = (settings.bridge_admin_token or "").strip()
        if not expected:
            raise HTTPException(status_code=404, detail="admin api disabled")
        got = request.headers.get("x-bridge-admin-token", "")
        if not secrets.compare_digest(got, expected):
            raise HTTPException(status_code=401, detail="unauthorized")
        data = await request.json()
        userids = data.get("userids") or []
        names = data.get("names") or {}
        if not isinstance(userids, list):
            raise HTTPException(400, "userids must be list")
        n = request.app.state.identity.import_userids(
            [str(u) for u in userids],
            {str(k): str(v) for k, v in names.items()} if isinstance(names, dict) else {},
        )
        return {"imported": n}

    return app


app = build_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
