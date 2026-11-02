# 职责：企微会话侧 L0/L1/L2/拒绝文案（对齐交互设计方案，不含 L4）。
"""出站文案模板。"""

from __future__ import annotations


def accepted(task_no: str, file_name: str | None = None) -> str:
    name = file_name or "材料"
    return f"已收到《{name}》，任务号 {task_no}。已启动合同录入协作，完成后将通知您确认。"


def stage(task_no: str, stage_name: str) -> str:
    return f"任务 {task_no}：{stage_name}。"


def need_confirm(task_no: str, confirm_url: str) -> str:
    return (
        f"任务 {task_no} 待确认：请核对预填字段并选择物料候选。\n"
        f"去确认：{confirm_url}"
    )


def draft_done(task_no: str, draft_url: str | None = None) -> str:
    extra = f"\n查看草稿：{draft_url}" if draft_url else ""
    return f"任务 {task_no} 录入协作已完成。请在控制台完成人工确认后，按公司流程提交会审。{extra}"


def need_file(task_no: str) -> str:
    return (
        f"任务 {task_no}：合同录入需要合同原件（PDF / Word / 图片）。"
        "请直接发送文件；文字说明可附在文件消息中。"
    )


def denied() -> str:
    return "您暂无权限使用合同助手，或账号已停用。如需开通请联系管理员。"


def failed(task_no: str, reason: str) -> str:
    return f"任务 {task_no} 未能完成：{reason}。您可重新发送文件或联系管理员，并提供本任务号。"


def still_running(task_no: str) -> str:
    return f"任务 {task_no}：仍在处理，请稍候。"
