# 职责：轮询 TeamRun / HITL，映射 L1 阶段文案并在待确认、终态时推企微。
"""合同录入协作进度监视。"""

from __future__ import annotations

import asyncio
import logging
import time

from app.config import Settings
from app.forge.client import ForgeClient, TeamRunRef
from app.messages import templates as msg
from app.ticket import token as ticket
from app.wecom.client import WeComClient

log = logging.getLogger("pipeline.monitor")

# pipeline 成员序号 → 业务阶段（对齐「雨中情-合同录入」四环）
_STAGE_LABEL = {
    0: "正在识别收件材料",
    1: "正在提取合同要素",
    2: "正在匹配物料清单",
    3: "正在整理缺件与填单草稿",
}

_TERMINAL = frozenset({"delivered", "failed", "escalated"})


async def watch_intake(
    *,
    settings: Settings,
    forge: ForgeClient,
    wecom: WeComClient,
    userid: str,
    task_no: str,
    tenant_id: str,
    owner_id: str,
    role: str,
    run: TeamRunRef,
) -> None:
    """后台监视一次录入 run：L1 阶段、首个 HITL 发「去确认」、终态结果。"""
    if settings.dry_run_forge:
        # 干跑：模拟四环进度后发待确认，便于联调企微文案
        for stage, label in _STAGE_LABEL.items():
            await wecom.send_text(userid, msg.stage(task_no, label))
            await asyncio.sleep(min(0.05, settings.run_poll_interval_sec))
        tok = ticket.issue(
            settings,
            tenant_id=tenant_id,
            owner_id=owner_id,
            session_id=run.session_id,
            run_id=run.run_id,
        )
        await wecom.send_text(userid, msg.need_confirm(task_no, ticket.confirm_url(settings, tok)))
        await wecom.send_text(userid, msg.draft_done(task_no))
        return

    started = time.monotonic()
    last_stage = -1
    confirmed = False
    last_nudge = 0.0

    while True:
        elapsed = time.monotonic() - started
        if elapsed > settings.run_poll_max_sec:
            await wecom.send_text(userid, msg.still_running(task_no))
            log.warning("run poll timeout task=%s run=%s", task_no, run.run_id)
            return

        try:
            cur = await forge.get_team_run(
                tenant_id=tenant_id,
                owner_id=owner_id,
                role=role,
                run_id=run.run_id,
            )
        except Exception:
            log.exception("get_team_run failed task=%s", task_no)
            await asyncio.sleep(settings.run_poll_interval_sec)
            continue

        if cur.stage != last_stage and cur.stage in _STAGE_LABEL:
            label = _STAGE_LABEL[cur.stage]
            await wecom.send_text(userid, msg.stage(task_no, label))
            last_stage = cur.stage
            last_nudge = time.monotonic()

        if not confirmed:
            try:
                pending = await forge.list_pending_approvals(
                    tenant_id=tenant_id,
                    owner_id=owner_id,
                    role=role,
                    run_id=run.run_id,
                )
            except Exception:
                log.exception("list approvals failed task=%s", task_no)
                pending = []
            if pending or (cur.stage >= 3 and cur.status == "running"):
                # 有 HITL，或已到缺件/草稿环：发确认深链（跳协作运行页）
                tok = ticket.issue(
                    settings,
                    tenant_id=tenant_id,
                    owner_id=owner_id,
                    session_id=cur.session_id or run.session_id,
                    run_id=run.run_id,
                )
                await wecom.send_text(
                    userid,
                    msg.need_confirm(task_no, ticket.confirm_url(settings, tok)),
                )
                confirmed = True

        if cur.status in _TERMINAL:
            if cur.status == "delivered":
                await wecom.send_text(userid, msg.draft_done(task_no))
            else:
                reason = ""
                if isinstance(cur.raw, dict):
                    reason = str(cur.raw.get("reason") or "")
                await wecom.send_text(
                    userid,
                    msg.failed(task_no, reason or f"协作结束：{cur.status}"),
                )
            return

        # 长时间无进展：补一条「仍在处理」
        if time.monotonic() - last_nudge > 120:
            await wecom.send_text(userid, msg.still_running(task_no))
            last_nudge = time.monotonic()

        await asyncio.sleep(settings.run_poll_interval_sec)
