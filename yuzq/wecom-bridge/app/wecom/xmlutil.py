# 职责：解析企微回调明文 XML，抽取消息字段。
"""回调明文 XML 解析。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass
class InboundMessage:
    """入站消息关键字段。"""

    corp_id: str
    userid: str
    msg_type: str
    msg_id: str | None
    content: str | None = None
    media_id: str | None = None
    file_name: str | None = None
    agent_id: str | None = None


def parse_message(xml_text: str, fallback_corp_id: str = "") -> InboundMessage:
    root = ET.fromstring(xml_text)
    text = lambda tag: (root.findtext(tag) or "").strip()
    msg_type = text("MsgType").lower()
    userid = text("FromUserName")
    corp = text("ToUserName") or fallback_corp_id
    return InboundMessage(
        corp_id=corp,
        userid=userid,
        msg_type=msg_type,
        msg_id=text("MsgId") or None,
        content=text("Content") or None,
        media_id=text("MediaId") or None,
        file_name=text("FileName") or None,
        agent_id=text("AgentID") or None,
    )
