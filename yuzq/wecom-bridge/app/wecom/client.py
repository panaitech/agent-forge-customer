# 职责：调用企业微信出站 API（access_token、素材下载、应用消息）。
"""企业微信 API 客户端。"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from app.config import Settings

log = logging.getLogger("wecom.client")


class WeComClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token: str | None = None
        self._expire_at: float = 0

    async def access_token(self) -> str:
        if self._token and time.time() < self._expire_at - 60:
            return self._token
        url = f"{self.settings.wecom_api_base}/cgi-bin/gettoken"
        params = {
            "corpid": self.settings.wecom_corp_id,
            "corpsecret": self.settings.wecom_secret,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"gettoken failed: {data}")
        self._token = data["access_token"]
        self._expire_at = time.time() + int(data.get("expires_in", 7200))
        return self._token

    async def download_media(self, media_id: str, dest: Path) -> Path:
        token = await self.access_token()
        url = f"{self.settings.wecom_api_base}/cgi-bin/media/get"
        max_bytes = self.settings.media_max_bytes
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url, params={"access_token": token, "media_id": media_id})
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            if "application/json" in ctype:
                raise RuntimeError(f"media get failed: {resp.text}")
            clen = resp.headers.get("content-length")
            if clen and int(clen) > max_bytes:
                raise RuntimeError(f"media too large: {clen} > {max_bytes}")
            body = resp.content
            if len(body) > max_bytes:
                raise RuntimeError(f"media too large: {len(body)} > {max_bytes}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
        return dest

    async def send_text(self, userid: str, content: str) -> None:
        if self.settings.dry_run_wecom_send:
            log.info("dry_run send_text to=%s content=%s", userid, content)
            return
        token = await self.access_token()
        url = f"{self.settings.wecom_api_base}/cgi-bin/message/send"
        body = {
            "touser": userid,
            "msgtype": "text",
            "agentid": self.settings.wecom_agent_id,
            "text": {"content": content},
            "safe": 0,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, params={"access_token": token}, json=body)
            resp.raise_for_status()
            data = resp.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"message/send failed: {data}")
