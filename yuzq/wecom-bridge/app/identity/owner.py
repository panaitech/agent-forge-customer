# 职责：按方案固定规则生成 Agent Forge owner_id（确定性，非手填对照）。
"""成员级归属 ID 生成。"""

from __future__ import annotations


def af_owner_id(corp_id: str, userid: str) -> str:
    """af_owner_id = wecom:{corp_id}:{userid}"""
    corp = corp_id.strip()
    user = userid.strip()
    if not corp or not user:
        raise ValueError("corp_id and userid are required")
    return f"wecom:{corp}:{user}"
