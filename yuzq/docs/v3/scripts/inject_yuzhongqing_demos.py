# 职责：向指定租户注入雨中情 v3 合同评审协作、租户私有 MCP 与作业 Skill。
# 不改 Runtime 默认 agentforge.jsonc，其它租户开箱看不见。
# 录入协作与 v2 相同；初审协作按 v3 方案扩展为基础初审、技术标注、商务标注、法务提示、卡片、执行提醒。
"""雨中情合同演示注入（v3 评审流水线）。

资产：
  - MCP 仍用 runtime demos/yuzhongqing-contract（本脚本只注册启动命令）
  - Skill 只读本目录 skills/，不改 runtime 里 v2 的 Skill
  - 本脚本只对 --tenant 注册 MCP / 写入 Skill / 建角色 / 建协作

两条协作（pipeline，写回须人工批准）：
  雨中情-合同录入
  雨中情-合同评审

示例：
  export AGENTFORGE_USER=alice
  export AGENTFORGE_PASSWORD='...'
  python inject_yuzhongqing_demos.py --tenant <租户> --base http://127.0.0.1:4196
  python inject_yuzhongqing_demos.py --tenant <租户> --only review
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_SKILLS = SCRIPT_DIR / "skills"

# 相对 packages/opencode（Instance.directory）的脚本路径，与龙源同构
MCP_NAME = "yuzhongqing-poc-contract"
DEFAULT_MCP_ARGS = ["../../demos/yuzhongqing-contract/mcp/contract-server.ts"]

READ = [
    {"permission": "read", "pattern": "*", "action": "allow"},
    {"permission": "grep", "pattern": "*", "action": "allow"},
    {"permission": "glob", "pattern": "*", "action": "allow"},
]
PERSIST = [{"permission": "edit", "pattern": "*", "action": "allow"}]
NO_EDIT = [{"permission": "edit", "pattern": "*", "action": "deny"}]
NO_DELEGATE = [{"permission": "task", "pattern": "*", "action": "deny"}]
DELEGATE = [{"permission": "task", "pattern": "*", "action": "allow"}]
NO_SHELL = [{"permission": "bash", "pattern": "*", "action": "deny"}]
NO_NET = [
    {"permission": "websearch", "pattern": "*", "action": "deny"},
    {"permission": "webfetch", "pattern": "*", "action": "deny"},
]
SKILL_ALLOW = [{"permission": "skill", "pattern": "*", "action": "allow"}]
ROLE_POLICY = {"default_ring": 0, "require_hitl": []}

POSITIONING = "面向企业 · 多智能体协作 · 业务自动化"
INTAKE_SKILL = "yuzhongqing-contract-intake-runbook"
REVIEW_SKILL = "yuzhongqing-contract-review-v3-runbook"
SKILL_NAMES = [INTAKE_SKILL, REVIEW_SKILL]


def mcp_allow(*tools: str) -> list[dict]:
    return [{"permission": f"{MCP_NAME}_{t}", "pattern": "*", "action": "allow"} for t in tools]


def mcp_ask(*tools: str) -> list[dict]:
    return [{"permission": f"{MCP_NAME}_{t}", "pattern": "*", "action": "ask"} for t in tools]


# 读数：模型只抽取和写说明，不把工具返回改写成另一套数字
CASE_RO = mcp_allow("list_cases", "get_case", "get_quote", "get_receipt", "search_material", "search_rule")
OCR_RO = mcp_allow("ocr_attachment")
MATCH_RO = mcp_allow("match_lines")
SETTLE_RO = mcp_allow("check_payment", "check_amounts")
DELIVERY_RO = mcp_allow("check_delivery")


def team_intake(role_ids: dict[str, str]) -> dict:
    """合同录入：收件 → 提取 → 清单匹配 → 缺件追问。G1 在写回工具上。"""
    return {
        "name": "雨中情-合同录入",
        "description": (
            "场景：销售拿到报价单或扫描件，要预填直供购销合同草稿。"
            "协作登记附件，抽出客户、项目、金额、付款、账期、收货、质保并带来源，"
            "物料清单只给 Top-3，缺字段列入追问；草稿落账须销售逐项确认。"
            "演示数据虚构。不接销售易，不定责，不盖章，不建单。"
        ),
        "start_prompt": (
            "案例 YZQ-2026-003，按契约跑完，写回须人批。"
            "交付物给销售看：字段、预填值、出处、待确认。不写工具名和置信度。"
            "扫描件没识别成时写「这次没识别成，对照的是预先准备的文字」。"
            "物料不能唯一命中时只给候选，不自动写内部编码。猜测不得写入正式字段。"
        ),
        "visibility": "tenant",
        "mode": "pipeline",
        "accept_criteria": "\n".join(
            [
                "1. 收件识别.md 登记附件是否齐全；没识别成时写明对照的是预先准备的文字，不写 source=fixture。",
                "2. 要素提取.md 每项含预填值、出处、待确认；无出处不写正式值；不写置信度。",
                "3. 清单匹配.md 含已对应、未对应、候选；第一个候选不得写成已对应。",
                "4. 填单草稿.md 按字段、预填值、出处、待确认列出；须人工批准后才算数。",
                "5. 文内可留一句演示数据声明；未做审批、用印、建单；正文无工具名。",
            ]
        ),
        "max_rounds": 3,
        "approval_policy": {"budget": 3, "supervisor_preauth": [], "auto_reuse": True},
        "enabled": True,
        "members": [
            {
                "role_id": role_ids["lead"],
                "duty": "负责录入链审计口径，不改单据",
                "is_supervisor": True,
            },
            {
                "role_id": role_ids["intake"],
                "duty": "第 1 环 - 收件识别",
                "order": 1,
                "output_contract": "收件识别.md：附件是否齐全、文字从哪来；不写工具名",
                "produces": ["收件识别.md"],
            },
            {
                "role_id": role_ids["extract"],
                "duty": "第 2 环 - 要素提取",
                "order": 2,
                "input_contract": "inputs/team/ 上游收件识别.md",
                "output_contract": "要素提取.md：字段、预填值、出处、待确认",
                "produces": ["要素提取.md"],
            },
            {
                "role_id": role_ids["match"],
                "duty": "第 3 环 - 清单匹配",
                "order": 3,
                "input_contract": "上游要素提取与报价行",
                "output_contract": "清单匹配.md：已对应、未对应、候选；不自动写内部编码",
                "produces": ["清单匹配.md"],
            },
            {
                "role_id": role_ids["ask"],
                "duty": "第 4 环 - 缺件追问与草稿（HITL）",
                "order": 4,
                "input_contract": "上游提取与匹配",
                "output_contract": "填单草稿.md：字段、预填值、出处、待确认；须人批",
                "produces": ["填单草稿.md"],
            },
        ],
    }


def team_review(role_ids: dict[str, str]) -> dict:
    """v3 评审：基础初审之后，技术、商务、法务同一波并行，再汇编卡片。"""
    return {
        "name": "雨中情-合同评审",
        "description": (
            "场景：合同进入评审后，先做基础初审；技术条款、商务风险、法务风险同时标注，"
            "三份到齐后写入同一张给评审人看的卡片，人工确认后才流转。"
            "基础字段用复算结果，写进文档时用白话，不写工具名。"
            "技术、商务、法务只写检索命中的条目，互不引用对方文件；没有条目编号的行不写。"
            "卡片不定责、不建议签署。执行与变更只做提醒，不写回。"
            "演示数据虚构。不盖章，不建单。"
        ),
        "start_prompt": (
            "案例 YZQ-2026-003。按成员契约跑完评审，写回须人批。"
            "第一次提交作业单必须一次列入全部六个执行岗。依赖以契约为准，不要改、不要漏。"
            "技术、商务、法务只依赖基础初审，因此同一波进行。卡片等这三份和基础初审都到齐再汇编。"
            "每一波对照验收标准通过即可，不要打回，不要自己写文件。各岗只交自己的那一个文件。"
            "交付物给评审人看：不写工具名、参数名、语料文件名。"
            "付款加总、行金额、地址只引用复算结果，不得自行加总后改结论，用白话写进文档。"
            "技术只查合同里出现的品名和项目名：双组分聚氨酯、非固化、屋面补强。查完即停。"
            "没有条目编号就不要写这一行，不要扩写成无法判断。"
            "评审卡片等三份标注和基础初审都到齐再汇编，不输出可签或不可签，不附未覆盖项清单。执行提醒不写回。"
        ),
        "visibility": "tenant",
        "mode": "supervisor",
        "accept_criteria": "\n".join(
            [
                "1. 基础初审.md 含产品、价格、交期、三单差异；合计与地址用白话写复算结果，无工具名。该岗只有这一个文件。",
                "2. 技术标注.md 只写有条目编号的行；不写无法判断清单，不判定方案合格。该岗只有这一个文件。",
                "3. 商务标注.md 只写有条目的付款、赔偿、违约、宽限期；不判断是否超权限。该岗只有这一个文件。",
                "4. 法务提示.md 只写有条目的行；标准号未写则待补，不定责、不给可签结论。该岗只有这一个文件。",
                "5. 评审卡片.md 在基础初审和三项标注都到齐后只汇编上游已有行，无未覆盖项清单；写回须人工批准。该岗只有这一个文件。",
                "6. 执行提醒.md 只列发货排产、补充协议、退换货的提醒，无写回。该岗只有这一个文件。",
                "7. 任一岗位出现其他岗位的文件，本岗验收不通过。",
            ]
        ),
        "max_rounds": 4,
        "approval_policy": {"budget": 3, "supervisor_preauth": [], "auto_reuse": True},
        "enabled": True,
        "members": [
            {
                "role_id": role_ids["lead"],
                "duty": "负责评审链审计口径，不改单据",
                "is_supervisor": True,
            },
            {
                "role_id": role_ids["basic"],
                "duty": "第 1 波 - 基础初审",
                "input_contract": "案例原文",
                "output_contract": "只交基础初审.md：事项、结论、白话说明；不写工具名和参数名",
                "produces": ["基础初审.md"],
            },
            {
                "role_id": role_ids["tech"],
                "duty": "第 2 波 - 技术条款标注",
                "needs": [role_ids["basic"]],
                "input_contract": "上游基础初审.md",
                "output_contract": "只交技术标注.md：只写有条目编号的行；不判定技术方案合格",
                "produces": ["技术标注.md"],
            },
            {
                "role_id": role_ids["biz"],
                "duty": "第 2 波 - 商务风险标注",
                "needs": [role_ids["basic"]],
                "input_contract": "上游基础初审.md",
                "output_contract": "只交商务标注.md：付款、赔偿、违约、宽限期；建议必须引用条目",
                "produces": ["商务标注.md"],
            },
            {
                "role_id": role_ids["legal"],
                "duty": "第 2 波 - 法务风险提示",
                "needs": [role_ids["basic"]],
                "input_contract": "上游基础初审.md",
                "output_contract": "只交法务提示.md：只写有条目的行；不定责、不建议签署",
                "produces": ["法务提示.md"],
            },
            {
                "role_id": role_ids["card"],
                "duty": "第 3 波 - 评审卡片（HITL）",
                "needs": [role_ids["basic"], role_ids["tech"], role_ids["biz"], role_ids["legal"]],
                "input_contract": "上游基础初审与三项标注",
                "output_contract": "只交评审卡片.md：只汇编上游已有行；须人批；不定责、不建议签署",
                "produces": ["评审卡片.md"],
            },
            {
                "role_id": role_ids["later"],
                "duty": "第 4 波 - 执行与变更提醒",
                "needs": [role_ids["card"]],
                "input_contract": "上游评审卡片",
                "output_contract": "只交执行提醒.md：只提醒，不写回，标明方案细化中",
                "produces": ["执行提醒.md"],
            },
        ],
    }


def _worker(
    key: str,
    name: str,
    description: str,
    persona: str,
    skill: str,
    permissions: list[dict],
    hitl: list[str] | None = None,
) -> dict:
    """执行岗：可读可写交付物，可调指定 MCP，不委派、不跑 shell。"""
    return {
        "key": key,
        "role": {
            "name": name,
            "description": description,
            "persona": persona,
            "capabilities": [
                "tool:read",
                "tool:grep",
                "tool:glob",
                "tool:skill",
                f"skill:{skill}",
                f"mcp:{MCP_NAME}",
            ],
            "permissions": [*READ, *PERSIST, *SKILL_ALLOW, *permissions, *NO_SHELL, *NO_NET, *NO_DELEGATE],
            "approval_policy": (
                {"default_ring": 1, "require_hitl": hitl} if hitl else ROLE_POLICY
            ),
            "memory_scope": "session",
            "enabled": True,
        },
    }


def _lead(key: str, name: str, description: str, persona: str) -> dict:
    """主管占位：只审计口径，不改单据，不调用 MCP。"""
    return {
        "key": key,
        "role": {
            "name": name,
            "description": description,
            "persona": persona,
            "capabilities": ["tool:read", "tool:grep", "tool:glob"],
            "permissions": [*READ, *NO_EDIT, *NO_SHELL, *NO_NET, *DELEGATE],
            "approval_policy": ROLE_POLICY,
            "memory_scope": "session",
            "enabled": True,
        },
    }


ROLES_INTAKE = [
    _lead(
        "lead",
        "雨中情-合同受理主管",
        "合同录入链负责人（不在接力环上，不改单据）",
        (
            f"你负责「雨中情-合同录入」流水线审计，主叙事对齐「{POSITIONING}」。"
            "你不亲自抽取、不改单据。确保收件→提取→匹配→追问按序完成，"
            "写回须人批。禁止审批通过、用印、建单。产出用简体中文。"
        ),
    ),
    _worker(
        "intake",
        "雨中情-收件识别员",
        "第 1 环：登记附件，扫描件走 OCR 或预置文本",
        (
            f"你是收件识别员。加载 skill {INTAKE_SKILL}。"
            "打开指定案例。扫描件做识别，机读报价单直接读文本。"
            "只写入收件识别.md：附件齐不齐、文字从哪来。禁止创建其他岗位的文件。"
            "没识别成时写「这次没识别成，对照的是预先准备的文字」。"
            "识别结果不是已确认字段。文档不写工具名。产出用简体中文。"
        ),
        INTAKE_SKILL,
        [*CASE_RO, *OCR_RO],
    ),
    _worker(
        "extract",
        "雨中情-要素提取员",
        "第 2 环：抽出合同要素，写下预填值和出处",
        (
            f"你是要素提取员。加载 skill {INTAKE_SKILL}。"
            "读上游收件识别，对照报价和合同原文，必要时查看栏目口径。"
            "只写入要素提取.md：客户、项目、金额、付款比例、账期、收货、质保。禁止创建其他岗位的文件。"
            "每项写预填值、出处、待确认。不写置信度。无出处不写正式值，缺项进缺口，不猜测。金额不心算。"
            "文档不写工具名。产出用简体中文。"
        ),
        INTAKE_SKILL,
        [*CASE_RO],
    ),
    _worker(
        "match",
        "雨中情-清单匹配员",
        "第 3 环：报价行对物料别名，给出 Top-3",
        (
            f"你是清单匹配员。加载 skill {INTAKE_SKILL}。"
            "报价行对物料别名。只写入清单匹配.md：已对应、未对应、候选。禁止创建其他岗位的文件。"
            "对上了写内部名称。不能唯一命中时，禁止把第一个候选写成已对应，禁止自动写内部编码，只列至多三个候选。"
            "文档不写工具名。产出用简体中文。"
        ),
        INTAKE_SKILL,
        [*CASE_RO, *MATCH_RO],
    ),
    _worker(
        "ask",
        "雨中情-缺件追问员",
        "第 4 环：追问清单、填单草稿、HITL 写回",
        (
            f"你是缺件追问员。加载 skill {INTAKE_SKILL}。"
            "汇总上游缺口，只按字段、预填值、出处、待确认写填单草稿.md，再提交并等待销售批准。禁止创建其他岗位的文件。"
            "待确认写「请销售确认」或「请销售补充」。猜测不得进入正式字段。不得绕过批准。"
            "文档不写工具名和置信度。产出用简体中文。"
        ),
        INTAKE_SKILL,
        [*CASE_RO, *MATCH_RO, *mcp_ask("upsert_contract_draft")],
        [f"{MCP_NAME}_upsert_contract_draft"],
    ),
]

ROLES_REVIEW = [
    _lead(
        "lead",
        "雨中情-评审链主管",
        "合同评审链负责人（不在接力环上，不改单据）",
        (
            f"你负责「雨中情-合同评审」，对齐「{POSITIONING}」。"
            "你不亲自改数、不改单据，也不自己写任何标注文件。"
            "第一次提交作业单必须一次列入全部六个执行岗，不要漏岗，不要拆开提交。"
            "依赖以成员契约为准：技术、商务、法务只依赖基础初审。每一波对照验收标准通过即可，不要打回，不要改岗位。"
            "写给评审人看的文档不出现工具名和参数名。条款只保留有条目编号的行，没有条目就不要写。"
            "卡片不定责、不建议签署，写回须人批。执行提醒不得写回。产出用简体中文。"
        ),
    ),
    _worker(
        "basic",
        "雨中情-基础初审员",
        "第 1 环：产品、价格、交期、三单与签收，结论用白话",
        (
            f"你是基础初审员。加载 skill {REVIEW_SKILL}。"
            "对照报价、合同、签收，用复算核对付款加总、行金额和地址。"
            "只写入基础初审.md：事项、结论（通过或不通过）、一句话说明。禁止创建其他岗位的文件。"
            "说明写成白话，例如四个节点加总 105、比 100 多 5，并写出两侧地址。"
            "禁止自行加总后改结论。禁止在文档里写工具名和参数名。产出用简体中文。"
        ),
        REVIEW_SKILL,
        [*CASE_RO, *SETTLE_RO, *DELIVERY_RO],
    ),
    _worker(
        "tech",
        "雨中情-技术标注员",
        "第 2 波：只按合同里的品名和项目名查技术条目",
        (
            f"你是技术标注员。加载 skill {REVIEW_SKILL}。"
            "只拿合同里出现的品名和项目名各查一次技术依据。003 查双组分聚氨酯、非固化、屋面补强，查完即停。"
            "不要搜验收、检测、包装、储运、方案是否合格、质保期。"
            "只把返回了条目编号的行写入技术标注.md。没有编号就不要写这一行。禁止创建其他岗位的文件。"
            "不编造标准，不判定技术方案合格。文档不写工具名。产出用简体中文。"
        ),
        REVIEW_SKILL,
        [*CASE_RO],
    ),
    _worker(
        "biz",
        "雨中情-商务标注员",
        "第 2 波：只标注有条目的付款、赔偿、违约、宽限期",
        (
            f"你是商务标注员。加载 skill {REVIEW_SKILL}。"
            "对照上游基础初审，查商务依据里的付款、赔偿、违约、宽限期。"
            "修改建议必须带回条目编号。没有条目编号的行不写，不要写成无法判断。"
            "付款加总只引用基础初审已经写明的结果。不判断授权是否超限，不决定上集团。"
            "只写入商务标注.md。禁止创建其他岗位的文件。文档不写工具名。产出用简体中文。"
        ),
        REVIEW_SKILL,
        [*CASE_RO, *SETTLE_RO],
    ),
    _worker(
        "legal",
        "雨中情-法务提示员",
        "第 2 波：只提示有条目的质保、验收、标准号和付款",
        (
            f"你是法务提示员。加载 skill {REVIEW_SKILL}。"
            "查法务依据。只写命中条目的行：质保年限、验收标准、标准号、付款比例。"
            "合同没写标准号时，结论写待补，说明里可以写具体标准号无法判断。"
            "依据里没有的题不要开。不定责，不输出可签或不可签。"
            "只写入法务提示.md。禁止创建其他岗位的文件。文档不写工具名。产出用简体中文。"
        ),
        REVIEW_SKILL,
        [*CASE_RO],
    ),
    _worker(
        "card",
        "雨中情-分层卡片员",
        "第 3 波：按骨架汇编上游已有行，HITL 写回",
        (
            f"你是分层卡片员。加载 skill {REVIEW_SKILL}。"
            "按作业标准里的卡片骨架，只把上游已经写出的行收成评审卡片.md。禁止创建其他岗位的文件。"
            "不要新开栏目，不要附未覆盖项清单，不要把没有条目编号的事项补成无法判断。"
            "文末写明：不改合同数字；不判断签署、盖章、建单、授权是否超限、技术方案是否合格；发货、补充协议、退换货只作提醒。"
            "再调用写回并等待人工批准。文档不写工具名和参数名。产出用简体中文。"
        ),
        REVIEW_SKILL,
        [*CASE_RO, *SETTLE_RO, *DELIVERY_RO, *mcp_ask("upsert_review_card")],
        [f"{MCP_NAME}_upsert_review_card"],
    ),
    _worker(
        "later",
        "雨中情-执行提醒员",
        "第 4 波：发货排产、补充协议、退换货只做提醒",
        (
            f"你是执行提醒员。加载 skill {REVIEW_SKILL}。"
            "读上游评审卡片，只写执行提醒.md：发货排产、补充协议、退换货各一行待细化提醒。禁止创建其他岗位的文件。"
            "标明方案仍在细化。不调用任何写回工具，不建单，不改单据。产出用简体中文。"
        ),
        REVIEW_SKILL,
        [*CASE_RO],
    ),
]

BUNDLES = {
    "intake": {"roles": ROLES_INTAKE, "team": team_intake},
    "review": {"roles": ROLES_REVIEW, "team": team_review},
}


def _basic_auth() -> tuple[str, str] | None:
    user = (os.environ.get("AGENTFORGE_USER") or os.environ.get("AGENTFORGE_USERNAME") or "").strip()
    password = (os.environ.get("AGENTFORGE_PASSWORD") or "").strip()
    if user and password:
        return user, password
    shared = (
        os.environ.get("AGENTFORGE_SERVER_PASSWORD") or os.environ.get("OPENCODE_SERVER_PASSWORD") or ""
    ).strip()
    if not shared:
        return None
    shared_user = (
        os.environ.get("AGENTFORGE_SERVER_USERNAME") or os.environ.get("OPENCODE_SERVER_USERNAME") or "agentforge"
    ).strip()
    return shared_user, shared


def _die_auth(base: str, status: int) -> None:
    print(
        f"Runtime 鉴权失败：{base} → {status}\n"
        "  export AGENTFORGE_USER=...\n"
        "  export AGENTFORGE_PASSWORD=...\n"
        "  python inject_yuzhongqing_demos.py --tenant <租户>",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _header_id(value: str) -> str:
    """与 runtime 约定：非 ASCII 租户 ID 须 percent-encode 后再进 HTTP 头。"""
    from urllib.parse import quote

    text = (value or "").strip()
    if not text:
        return text
    if all(ch.isascii() and (ch.isalnum() or ch in "._-") for ch in text):
        return text
    return quote(text, safe="-_.!~*'()")


class Client:
    """控制台 HTTP。租户头把 MCP、Skill、角色、协作都写进指定租户。"""

    def __init__(self, base: str, tenant: str, role: str, auth: tuple[str, str] | None) -> None:
        self.base = base.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "X-AgentForge-Tenant-Id": _header_id(tenant),
            "X-AgentForge-Role": role,
            "X-AgentForge-Channel": "console",
        }
        if auth:
            token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
            self.headers["Authorization"] = f"Basic {token}"

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw.decode()) if raw else None
        except urllib.error.HTTPError as err:
            raw = err.read().decode(errors="replace")
            try:
                parsed: object = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = raw
            return err.code, parsed


def _must(status: int, payload: object, what: str) -> dict:
    if status == 401:
        return {}
    if status >= 400 or not isinstance(payload, dict):
        print(f"错误：{what} 失败 {status} {payload}", file=sys.stderr)
        raise SystemExit(2)
    return payload


def skills_dir() -> Path:
    """v3 只读本目录 skills，避免覆盖 runtime 里 v2 的作业标准。"""
    return LOCAL_SKILLS


def ensure_mcp(client: Client) -> None:
    """按租户注册 local MCP。语料默认用包内 v3-corpus，这里不再改目录。"""
    script = os.environ.get("YUZHONGQING_MCP_SCRIPT", "").strip()
    args = [script] if script else list(DEFAULT_MCP_ARGS)
    body = {
        "name": MCP_NAME,
        "config": {
            "type": "local",
            "command": ["bun", "run", *args],
            "enabled": True,
            "timeout": 30000,
        },
    }
    status, payload = client.call("POST", "/mcp", body)
    if status == 401:
        _die_auth(client.base, status)
    if status >= 400:
        print(f"警告：注册 MCP 失败 {status} {payload}", file=sys.stderr)
    else:
        print(f"mcp {MCP_NAME} registered (tenant-scoped) command={body['config']['command']}")
    share_status, _ = client.call("POST", f"/mcp/{MCP_NAME}/share")
    if share_status >= 400 and share_status != 409:
        print(f"提示：MCP share 状态 {share_status}（若仅本人跑协作可忽略）", file=sys.stderr)


def ensure_skills(client: Client) -> None:
    root = skills_dir()
    if not root.is_dir():
        print(f"错误：找不到 Skill 目录 {root}", file=sys.stderr)
        raise SystemExit(2)
    print(f"skills from {root}")
    status, existing = client.call("GET", "/skill")
    if status == 401:
        _die_auth(client.base, status)
    by_name: dict[str, dict] = {}
    if isinstance(existing, list):
        for row in existing:
            if isinstance(row, dict) and row.get("name"):
                by_name[str(row["name"])] = row
    for name in SKILL_NAMES:
        path = root / name / "SKILL.md"
        if not path.is_file():
            print(f"错误：缺少 {path}", file=sys.stderr)
            raise SystemExit(2)
        content = path.read_text(encoding="utf-8")
        desc = name
        for line in content.splitlines()[:20]:
            if line.startswith("description:"):
                desc = line.split(":", 1)[1].strip()
                break
        if name in by_name:
            status, saved = client.call("PUT", f"/skill/{name}", {"description": desc, "content": content})
        else:
            status, saved = client.call(
                "POST", "/skill", {"name": name, "description": desc, "content": content}
            )
        if status == 401:
            _die_auth(client.base, status)
        _must(status, saved if isinstance(saved, dict) else {"ok": True}, f"skill {name}")
        share_status, _ = client.call("POST", f"/skill/{name}/share")
        if share_status >= 400 and share_status != 409:
            print(f"警告：skill {name} share {share_status}", file=sys.stderr)
        print(f"skill {name} ok")


def upsert_roles(client: Client, specs: list[dict]) -> dict[str, str]:
    status, existing = client.call("GET", "/agent")
    if status == 401:
        _die_auth(client.base, status)
    if status >= 400 or not isinstance(existing, list):
        print(f"错误：列出角色失败 {status} {existing}", file=sys.stderr)
        raise SystemExit(2)
    by_name: dict[str, dict] = {}
    for row in existing:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        prev = by_name.get(name)
        if prev is None or int(row.get("time_updated") or 0) >= int(prev.get("time_updated") or 0):
            by_name[name] = row
    role_ids: dict[str, str] = {}
    for spec in specs:
        body = dict(spec["role"])
        found = by_name.get(body["name"])
        if found:
            status, saved = client.call("PUT", f"/agent/{found['id']}", body)
        else:
            status, saved = client.call("POST", "/agent", body)
        if status == 401:
            _die_auth(client.base, status)
        saved = _must(status, saved, f"角色 {body['name']}")
        role_ids[spec["key"]] = str(saved["id"])
        share_status, _ = client.call("POST", f"/agent/{saved['id']}/share")
        if share_status >= 400 and share_status != 409:
            print(f"警告：角色 {body['name']} share {share_status}", file=sys.stderr)
        print(f"role {body['name']} -> {role_ids[spec['key']]}")
    return role_ids


def upsert_team(client: Client, payload: dict) -> None:
    status, teams = client.call("GET", "/team")
    if status == 401:
        _die_auth(client.base, status)
    if status >= 400 or not isinstance(teams, list):
        print(f"错误：列出协作失败 {status} {teams}", file=sys.stderr)
        raise SystemExit(2)
    found = next((row for row in teams if isinstance(row, dict) and row.get("name") == payload["name"]), None)
    if found:
        status, saved = client.call("PUT", f"/team/{found['id']}", payload)
    else:
        status, saved = client.call("POST", "/team", payload)
    if status == 401:
        _die_auth(client.base, status)
    saved = _must(status, saved, f"协作 {payload['name']}")
    print(f"team {payload['name']} -> {saved.get('id')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject Yuzhongqing contract demo teams into one tenant")
    parser.add_argument("--base", default=os.environ.get("RUNTIME_BASE_URL", "http://127.0.0.1:4096"))
    parser.add_argument("--tenant", default=os.environ.get("AGENTFORGE_TENANT", ""))
    parser.add_argument("--role", default=os.environ.get("AGENTFORGE_ROLE", "admin"))
    parser.add_argument(
        "--only",
        choices=["intake", "review", "all"],
        default="all",
        help="inject one bundle or all (default)",
    )
    parser.add_argument("--skip-mcp", action="store_true", help="skip POST /mcp")
    parser.add_argument("--skip-skills", action="store_true", help="skip skill upsert")
    args = parser.parse_args()
    tenant = args.tenant.strip()
    if not tenant:
        print("请用 --tenant 或 AGENTFORGE_TENANT 指定租户。", file=sys.stderr)
        raise SystemExit(2)

    auth = _basic_auth()
    if auth is None:
        print("警告：未设置 AGENTFORGE_USER/PASSWORD，若需认证将 401。", file=sys.stderr)
    client = Client(args.base, tenant, args.role.strip() or "admin", auth)

    if not args.skip_mcp:
        ensure_mcp(client)
    if not args.skip_skills:
        ensure_skills(client)

    keys = list(BUNDLES) if args.only == "all" else [args.only]
    for key in keys:
        bundle = BUNDLES[key]
        print(f"==> bundle {key}")
        role_ids = upsert_roles(client, bundle["roles"])
        upsert_team(client, bundle["team"](role_ids))
    print(f"完成 tenant={tenant} mcp={MCP_NAME}")


if __name__ == "__main__":
    main()
