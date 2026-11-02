# 职责：入站流水线——身份、附件、启动「雨中情-合同录入」协作、L0 受理；进度由 monitor 推送。
"""企微入站业务流水线（合同录入完整链路）。"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.forge.client import ForgeClient, OwnerMismatchError, TeamNotFoundError
from app.identity.service import IdentityDenied, IdentityService
from app.messages import templates as msg
from app.pipeline.monitor import watch_intake
from app.wecom.client import WeComClient
from app.wecom.xmlutil import InboundMessage

log = logging.getLogger("pipeline.inbound")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


@dataclass
class InboundResult:
    """流水线结果。"""

    task_no: str
    session_id: str | None
    reply_text: str
    replay: bool = False
    run_id: str | None = None


@dataclass
class Claim:
    """幂等占位结果。"""

    is_new: bool
    task_no: str
    session_id: str | None
    run_id: str | None = None


class TaskStore:
    """消息幂等：先占位 msg_id，再绑定 session/run，避免并发双建。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=30) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inbound_task (
                  msg_id TEXT PRIMARY KEY,
                  task_no TEXT NOT NULL,
                  session_id TEXT,
                  run_id TEXT,
                  userid TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                )
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(inbound_task)")}
            if "run_id" not in cols:
                conn.execute("ALTER TABLE inbound_task ADD COLUMN run_id TEXT")

    def claim(self, msg_id: str, userid: str, task_no: str) -> Claim:
        with sqlite3.connect(self.path, timeout=30) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT task_no, session_id, run_id FROM inbound_task WHERE msg_id=?",
                (msg_id,),
            ).fetchone()
            if row:
                conn.execute("COMMIT")
                return Claim(False, row[0], row[1], row[2])
            conn.execute(
                """
                INSERT INTO inbound_task (msg_id, task_no, session_id, run_id, userid, created_at)
                VALUES (?, ?, NULL, NULL, ?, ?)
                """,
                (msg_id, task_no, userid, int(time.time())),
            )
            conn.execute("COMMIT")
            return Claim(True, task_no, None, None)

    def bind_run(self, msg_id: str, session_id: str, run_id: str) -> None:
        with sqlite3.connect(self.path, timeout=30) as conn:
            conn.execute(
                "UPDATE inbound_task SET session_id=?, run_id=? WHERE msg_id=?",
                (session_id, run_id, msg_id),
            )


class InboundPipeline:
    def __init__(
        self,
        settings: Settings,
        identity: IdentityService,
        wecom: WeComClient,
        forge: ForgeClient,
        tasks: TaskStore,
    ) -> None:
        self.settings = settings
        self.identity = identity
        self.wecom = wecom
        self.forge = forge
        self.tasks = tasks

    def _task_no(self) -> str:
        return f"YZQ-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    def _safe_filename(self, name: str | None) -> str:
        raw = (name or "attachment.bin").strip() or "attachment.bin"
        base = Path(raw).name
        cleaned = _SAFE_NAME.sub("_", base)[:180]
        return cleaned or "attachment.bin"

    def _intake_prompt(self, *, task_no: str, userid: str, file_name: str | None, extra: str | None) -> str:
        """启动录入协作时注入主管/成员计划的业务提示（对齐 inject start_prompt 口径）。"""
        lines = [
            f"企微合同录入任务 {task_no}。",
            "source=wecom",
            f"userid={userid}",
            "按契约跑完四环：收件识别 → 要素提取 → 清单匹配 → 缺件追问与填单草稿。",
            "写回须人批。交付物给销售看：字段、预填值、出处、待确认。不写工具名和置信度。",
            "物料不能唯一命中时只给候选，不自动写内部编码。猜测不得写入正式字段。",
            "扫描件没识别成时写「这次没识别成，对照的是预先准备的文字」。",
        ]
        if file_name:
            lines.append(f"附件文件名：{file_name}")
        if extra and extra.strip():
            lines.append(f"用户补充说明：\n{extra.strip()}")
        return "\n".join(lines)

    async def handle(self, message: InboundMessage) -> InboundResult:
        task_no = self._task_no()
        claim: Claim | None = None
        if message.msg_id:
            claim = self.tasks.claim(message.msg_id, message.userid, task_no)
            task_no = claim.task_no
            if not claim.is_new:
                text = msg.accepted(task_no, message.file_name)
                if claim.session_id or claim.run_id:
                    await self.wecom.send_text(message.userid, text)
                else:
                    await self.wecom.send_text(message.userid, msg.still_running(task_no))
                return InboundResult(
                    task_no=task_no,
                    session_id=claim.session_id,
                    run_id=claim.run_id,
                    reply_text=text,
                    replay=True,
                )

        try:
            ident = self.identity.ensure_member(message.userid)
        except IdentityDenied:
            text = msg.denied()
            await self.wecom.send_text(message.userid, text)
            return InboundResult(task_no=task_no, session_id=None, reply_text=text)

        # L0：尽快受理，再启动协作
        accept = msg.accepted(task_no, message.file_name)
        await self.wecom.send_text(message.userid, accept)

        # 仅文本且无附件：提示发文件（录入主路径需要合同材料）
        if message.msg_type == "text" and not message.media_id:
            text = msg.need_file(task_no)
            await self.wecom.send_text(message.userid, text)
            return InboundResult(task_no=task_no, session_id=None, reply_text=text)

        files_payload: list[dict[str, str]] = []
        fname: str | None = None
        if message.msg_type in {"file", "image"} and message.media_id:
            fname = self._safe_filename(message.file_name)
            dest = self.settings.attachments_dir() / task_no / fname
            try:
                await self.wecom.download_media(message.media_id, dest)
                uploaded = await self.forge.upload_sandbox(
                    tenant_id=ident.tenant_id,
                    owner_id=ident.owner_id,
                    role=ident.role,
                    session_id=None,
                    path=dest,
                    file_name=fname,
                )
                if not uploaded.data_url:
                    raise RuntimeError("sandbox.upload missing data_url")
                files_payload.append(
                    {
                        "filename": uploaded.filename,
                        "mime": uploaded.mime,
                        "url": uploaded.data_url,
                    }
                )
            except Exception:
                log.exception("media handling failed task=%s", task_no)
                fail = msg.failed(task_no, "附件处理失败，可重新发送文件")
                await self.wecom.send_text(message.userid, fail)
                return InboundResult(task_no=task_no, session_id=None, reply_text=fail)

        try:
            team = await self.forge.resolve_intake_team(
                tenant_id=ident.tenant_id,
                owner_id=ident.owner_id,
                role=ident.role,
            )
        except TeamNotFoundError as err:
            log.error("intake team missing: %s", err)
            fail = msg.failed(task_no, "未配置合同录入协作，请联系管理员注入「雨中情-合同录入」")
            await self.wecom.send_text(message.userid, fail)
            return InboundResult(task_no=task_no, session_id=None, reply_text=fail)

        prompt = self._intake_prompt(
            task_no=task_no,
            userid=message.userid,
            file_name=fname,
            extra=message.content if message.msg_type == "text" else None,
        )

        try:
            run = await self.forge.start_team_run(
                tenant_id=ident.tenant_id,
                owner_id=ident.owner_id,
                role=ident.role,
                team_id=team.team_id,
                prompt=prompt,
                files=files_payload or None,
            )
        except OwnerMismatchError as err:
            log.error("owner mismatch: %s", err)
            fail = msg.failed(task_no, "身份归属配置错误，请联系管理员")
            await self.wecom.send_text(message.userid, fail)
            return InboundResult(task_no=task_no, session_id=None, reply_text=fail)
        except Exception:
            log.exception("start intake team failed task=%s", task_no)
            fail = msg.failed(task_no, "启动合同录入协作失败")
            await self.wecom.send_text(message.userid, fail)
            return InboundResult(task_no=task_no, session_id=None, reply_text=fail)

        if message.msg_id:
            self.tasks.bind_run(message.msg_id, run.session_id, run.run_id)

        log.info(
            "intake started task=%s team=%s run=%s session=%s",
            task_no,
            team.team_id,
            run.run_id,
            run.session_id,
        )

        # 进度监视（L1 / HITL / 终态）；回调已在 background task 中，可长时间 await
        await watch_intake(
            settings=self.settings,
            forge=self.forge,
            wecom=self.wecom,
            userid=message.userid,
            task_no=task_no,
            tenant_id=ident.tenant_id,
            owner_id=ident.owner_id,
            role=ident.role,
            run=run,
        )

        return InboundResult(
            task_no=task_no,
            session_id=run.session_id,
            run_id=run.run_id,
            reply_text=accept,
        )
