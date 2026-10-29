# 职责：向指定租户注入雨中情两条合同演示协作、租户私有 MCP 与作业 Skill。
# 不改 Runtime 默认 agentforge.jsonc，其它租户开箱看不见。
"""雨中情合同演示注入（非控制台预置场景）。

资产：
  - MCP 进程计划放在 runtime demos/yuzhongqing-contract（本脚本只注册启动命令）
  - Skill 优先读 runtime 该目录；尚未落地时读本目录 skills/
  - 本脚本只对 --tenant 注册 MCP / 写入 Skill / 建角色 / 建协作

两条协作（pipeline，写回须人工批准）：
  雨中情-合同录入
  雨中情-合同初审

示例：
  export AGENTFORGE_USER=alice
  export AGENTFORGE_PASSWORD='...'
  python inject_yuzhongqing_demos.py --tenant <租户> --base http://127.0.0.1:4196
  python inject_yuzhongqing_demos.py --tenant <租户> --only intake
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


def docs_root() -> Path:
    """脚本在 v2/scripts，上溯到 agent-forge-docs，再找兄弟仓 runtime。"""
    for parent in SCRIPT_DIR.parents:
        if parent.name == "agent-forge-docs":
            return parent
    raise SystemExit("找不到 agent-forge-docs 根目录")


DOCS_ROOT = docs_root()
RUNTIME_ROOT = Path(
    os.environ.get("AGENTFORGE_RUNTIME_ROOT") or (DOCS_ROOT.parent / "agent-forge-runtime")
).resolve()
DEMOS = RUNTIME_ROOT / "demos" / "yuzhongqing-contract"
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
REVIEW_SKILL = "yuzhongqing-contract-review-runbook"
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
            "案例 YZQ-2026-003，按契约跑完，写回须人批，标明演示虚构数据。"
            "扫描件走 ocr_attachment；source=fixture 时写明预置文本。"
            "物料不能唯一命中时只给 Top-3，不自动落编码。猜测不得写入正式字段。"
        ),
        "visibility": "tenant",
        "mode": "pipeline",
        "accept_criteria": "\n".join(
            [
                "1. 收件识别.md 登记附件是否齐全；OCR 回退时写明 source=fixture。",
                "2. 要素提取.md 每项含值、置信度、出处；无出处不写正式值。",
                "3. 清单匹配.md 含已匹配、未匹配、Top-3；Top-3 第一条不得写成已匹配。",
                "4. 填单草稿.md 列出追问；upsert_contract_draft 须人工批准后才落账。",
                "5. 文内标明演示虚构数据；未做审批、用印、建单。",
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
                "output_contract": "收件识别.md：附件是否齐全、文本来源（ocr 或 fixture）",
                "produces": ["收件识别.md"],
            },
            {
                "role_id": role_ids["extract"],
                "duty": "第 2 环 - 要素提取",
                "order": 2,
                "input_contract": "inputs/team/ 上游收件识别.md",
                "output_contract": "要素提取.md：字段、值、置信度、出处、校验结果",
                "produces": ["要素提取.md"],
            },
            {
                "role_id": role_ids["match"],
                "duty": "第 3 环 - 清单匹配",
                "order": 3,
                "input_contract": "上游要素提取与报价行",
                "output_contract": "清单匹配.md：已匹配、未匹配、Top-3；不自动落编码",
                "produces": ["清单匹配.md"],
            },
            {
                "role_id": role_ids["ask"],
                "duty": "第 4 环 - 缺件追问与草稿（HITL）",
                "order": 4,
                "input_contract": "上游提取与匹配",
                "output_contract": "填单草稿.md；upsert_contract_draft 须人批",
                "produces": ["填单草稿.md"],
            },
        ],
    }


def team_review(role_ids: dict[str, str]) -> dict:
    """区域初审：三单 → 结算复算 → 签收 → 评审卡片。G2 在写回工具上。"""
    return {
        "name": "雨中情-合同初审",
        "description": (
            "场景：区域商务对已确认的合同草稿做初审。"
            "协作比对报价、合同草稿、物料映射，用规则工具复算付款比例是否为 100%，"
            "核对收货信息与签收单，汇总评审卡片。"
            "卡片只标通过 / 不通过 / 待核，不定责，不建议签署。"
            "演示数据虚构。不做法务定责，不盖章，不建单。"
        ),
        "start_prompt": (
            "案例 YZQ-2026-003。从该案例的报价、合同草稿、物料映射、签收单跑完初审。"
            "按契约跑完，写回须人批，标明演示虚构数据。"
            "付款合计与差额只引用 check_payment，数量金额只引用 check_amounts，"
            "地址是否一致只引用 check_delivery。不得自行加总后改结论。"
            "评审卡片不输出可签或不可签，不建议签署。"
        ),
        "visibility": "tenant",
        "mode": "pipeline",
        "accept_criteria": "\n".join(
            [
                "1. 三单比对.md 对照报价、合同草稿、物料映射，差异带来源。",
                "2. 结算校验.md 的合计与差额来自 check_payment / check_amounts，不是模型口述。",
                "3. 签收核对.md 的一致与否来自 check_delivery。",
                "4. 评审卡片.md 含红黄绿、原文位置、规则编号；写明不定责、不建议签署。",
                "5. upsert_review_card 须人工批准；未做用印与建单。",
            ]
        ),
        "max_rounds": 3,
        "approval_policy": {"budget": 3, "supervisor_preauth": [], "auto_reuse": True},
        "enabled": True,
        "members": [
            {
                "role_id": role_ids["lead"],
                "duty": "负责初审链审计口径，不改单据",
                "is_supervisor": True,
            },
            {
                "role_id": role_ids["cmp"],
                "duty": "第 1 环 - 三单比对",
                "order": 1,
                "output_contract": "三单比对.md：报价、草稿、物料映射的差异与出处",
                "produces": ["三单比对.md"],
            },
            {
                "role_id": role_ids["settle"],
                "duty": "第 2 环 - 结算复算",
                "order": 2,
                "input_contract": "上游三单比对与案例单据",
                "output_contract": "结算校验.md：只引用规则工具返回的合计、差额、行金额",
                "produces": ["结算校验.md"],
            },
            {
                "role_id": role_ids["recv"],
                "duty": "第 3 环 - 签收核对",
                "order": 3,
                "input_contract": "上游单据与结算结论",
                "output_contract": "签收核对.md：只引用 check_delivery",
                "produces": ["签收核对.md"],
            },
            {
                "role_id": role_ids["card"],
                "duty": "第 4 环 - 评审卡片（HITL）",
                "order": 4,
                "input_contract": "上游三单、结算、签收",
                "output_contract": "评审卡片.md；upsert_review_card 须人批；不定责、不建议签署",
                "produces": ["评审卡片.md"],
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
            "用 list_cases / get_case 打开指定案例。扫描件调用 ocr_attachment，"
            "机读报价单直接读文本。写入收件识别.md，标明文本来源；"
            "source=fixture 时写明预置文本。识别结果不是已确认字段。产出用简体中文。"
        ),
        INTAKE_SKILL,
        [*CASE_RO, *OCR_RO],
    ),
    _worker(
        "extract",
        "雨中情-要素提取员",
        "第 2 环：抽出合同要素并带来源与置信度",
        (
            f"你是要素提取员。加载 skill {INTAKE_SKILL}。"
            "读上游收件识别，用 get_case / get_quote 取原文，必要时 search_rule 查看栏目口径。"
            "写入要素提取.md：客户、项目、金额、付款比例、账期、收货、质保。"
            "每项含置信度与出处。无出处不写正式值，缺项进缺口，不猜测。金额不心算。产出用简体中文。"
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
            "用 search_material 与 match_lines。写入清单匹配.md：已匹配、未匹配、Top-3。"
            "不能唯一命中时，禁止把 Top-3 第一条写成已匹配，禁止自动落内部编码。"
            "声明别名表是假设口径。产出用简体中文。"
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
            "汇总上游缺口，写填单草稿.md，再调用 upsert_contract_draft 并等待人工批准。"
            "猜测不得进入正式字段。不得绕过审批。产出用简体中文。"
        ),
        INTAKE_SKILL,
        [*CASE_RO, *MATCH_RO, *mcp_ask("upsert_contract_draft")],
        [f"{MCP_NAME}_upsert_contract_draft"],
    ),
]

ROLES_REVIEW = [
    _lead(
        "lead",
        "雨中情-区域初审主管",
        "区域初审链负责人（不在接力环上，不改单据）",
        (
            f"你负责「雨中情-合同初审」，对齐「{POSITIONING}」。"
            "你不亲自改数、不改单据。确保三单→结算→签收→卡片按序完成，"
            "结算数字来自规则工具，卡片不定责、不建议签署，写回须人批。产出用简体中文。"
        ),
    ),
    _worker(
        "cmp",
        "雨中情-三单比对员",
        "第 1 环：报价、合同草稿、物料映射对照",
        (
            f"你是三单比对员。加载 skill {REVIEW_SKILL}。"
            "用 get_case / get_quote / get_receipt / search_material 对照三单。"
            "写入三单比对.md，差异写明两侧的值与出处。标准条款只提示缺失，不改写。产出用简体中文。"
        ),
        REVIEW_SKILL,
        [*CASE_RO],
    ),
    _worker(
        "settle",
        "雨中情-结算复算员",
        "第 2 环：只引用规则工具的付款比例与行金额",
        (
            f"你是结算复算员。加载 skill {REVIEW_SKILL}。"
            "调用 check_payment 与 check_amounts，把合计、差额、行校验原样写入结算校验.md。"
            "禁止自行加总后改结论。工具失败则标不通过。产出用简体中文。"
        ),
        REVIEW_SKILL,
        [*CASE_RO, *SETTLE_RO],
    ),
    _worker(
        "recv",
        "雨中情-签收核对员",
        "第 3 环：合同收货信息与签收单",
        (
            f"你是签收核对员。加载 skill {REVIEW_SKILL}。"
            "调用 check_delivery，写入签收核对.md。一致与否只引用工具返回，并抄出两侧收货信息。产出用简体中文。"
        ),
        REVIEW_SKILL,
        [*CASE_RO, *DELIVERY_RO],
    ),
    _worker(
        "card",
        "雨中情-评审卡片员",
        "第 4 环：评审卡片 + HITL 写回",
        (
            f"你是评审卡片员。加载 skill {REVIEW_SKILL}。"
            "汇总上游为评审卡片.md：红黄绿、原文位置、规则编号。"
            "文内写明不定责、不建议签署，不出现可签或不可签。"
            "再调用 upsert_review_card 并等待人工批准。不得绕过审批。产出用简体中文。"
        ),
        REVIEW_SKILL,
        [*CASE_RO, *SETTLE_RO, *DELIVERY_RO, *mcp_ask("upsert_review_card")],
        [f"{MCP_NAME}_upsert_review_card"],
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


class Client:
    """控制台 HTTP。租户头把 MCP、Skill、角色、协作都写进指定租户。"""

    def __init__(self, base: str, tenant: str, role: str, auth: tuple[str, str] | None) -> None:
        self.base = base.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "X-AgentForge-Tenant-Id": tenant,
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
    """runtime 演示包里已有 SKILL.md 时用它；否则用本脚本旁的 skills/。"""
    runtime = DEMOS / "skills"
    if runtime.is_dir() and any(runtime.glob("*/SKILL.md")):
        return runtime
    return LOCAL_SKILLS


def ensure_mcp(client: Client) -> None:
    """按租户注册 local MCP。服务端代码未落地时，这里只写入启动命令。"""
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
