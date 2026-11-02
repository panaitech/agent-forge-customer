# 职责：签发与校验短时确认深链 ticket（绑定 tenant/owner/session/run）。
"""确认深链 ticket。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import urlencode

from app.config import Settings


@dataclass
class TicketPayload:
    tenant_id: str
    owner_id: str
    session_id: str
    exp: int
    run_id: str | None = None


class TicketError(Exception):
    """ticket 无效或过期。"""


def _sign(secret: str, body: str) -> str:
    dig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(dig).decode("ascii").rstrip("=")


def issue(
    settings: Settings,
    *,
    tenant_id: str,
    owner_id: str,
    session_id: str,
    run_id: str | None = None,
) -> str:
    payload = {
        "tenant_id": tenant_id,
        "owner_id": owner_id,
        "session_id": session_id,
        "exp": int(time.time()) + settings.ticket_ttl_sec,
    }
    if run_id:
        payload["run_id"] = run_id
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return f"{raw}.{_sign(settings.ticket_secret, raw)}"


def verify(settings: Settings, token: str) -> TicketPayload:
    try:
        raw, sig = token.rsplit(".", 1)
    except ValueError as err:
        raise TicketError("malformed") from err
    if not hmac.compare_digest(_sign(settings.ticket_secret, raw), sig):
        raise TicketError("bad signature")
    try:
        pad = "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(raw + pad))
    except Exception as err:
        raise TicketError("bad payload") from err
    exp = int(data.get("exp") or 0)
    if exp < int(time.time()):
        raise TicketError("expired")
    run = data.get("run_id")
    return TicketPayload(
        tenant_id=str(data["tenant_id"]),
        owner_id=str(data["owner_id"]),
        session_id=str(data["session_id"]),
        exp=exp,
        run_id=str(run) if run else None,
    )


def confirm_url(settings: Settings, token: str) -> str:
    """控制台确认深链；经 Bridge /confirm 兑换后跳到协作运行页或会话。"""
    base = settings.public_base_url.rstrip("/")
    return f"{base}/confirm?{urlencode({'ticket': token})}"
