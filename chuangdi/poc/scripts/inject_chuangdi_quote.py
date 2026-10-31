# 职责：向指定租户注入创迪情报板报价协作与作业 Skill（无 MCP）。
# 不改 Runtime 默认 agentforge.jsonc，其它租户开箱看不见。
# 形态对齐雨中情 v3 的 Skill/角色/协作注入，但不注册 MCP。
"""创迪报价注入（附件 + Skill）。

资产：
  - Skill：只读本目录 skills/
  - 本脚本只对 --tenant 写入 Skill / 建角色 / 建协作

一条协作（pipeline）：
  创迪-情报板报价

任务须上传招标 PDF、规格单价表、核算口径表。
解析岗通读招标书自动抽取；末岗产出报价单.md；用户若要求 Word/PDF，优先平台 skill，不够则工作区写代码。

示例：
  export AGENTFORGE_USER=alice
  export AGENTFORGE_PASSWORD='...'
  python3 inject_chuangdi_quote.py --tenant <租户> --base http://127.0.0.1:4196
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
SHELL = [{"permission": "bash", "pattern": "*", "action": "allow"}]
NO_NET = [
    {"permission": "websearch", "pattern": "*", "action": "deny"},
    {"permission": "webfetch", "pattern": "*", "action": "deny"},
]
SKILL_ALLOW = [{"permission": "skill", "pattern": "*", "action": "allow"}]
ROLE_POLICY = {"default_ring": 0, "require_hitl": []}
# 平台预置：控制台安装后可供报价单岗按用户要求调用
PDF_SKILL = "pdf"
DOCX_SKILL = "docx"

RUNBOOK = "chuangdi-quote-runbook"
PARSE_SKILL = "chuangdi-quote-parse"
REVIEW_SKILL = "chuangdi-quote-review"
SCOPE_SKILL = "chuangdi-quote-scope"
PRICE_SKILL = "chuangdi-quote-price"
SHEET_SKILL = "chuangdi-quote-sheet"
SKILL_NAMES = [RUNBOOK, SCOPE_SKILL, PARSE_SKILL, REVIEW_SKILL, PRICE_SKILL, SHEET_SKILL]


def team_quote(role_ids: dict[str, str]) -> dict:
    """解析 → 复核 → 读表 → 计价 → 物料核对 → 正式报价单。"""
    return {
        "name": "创迪-情报板报价",
        "description": (
            "场景：任务已上传招标 PDF、规格单价表与核算口径表（不上传大模组核算原表）。"
            "三件套：规格单价表 + 核算口径表（BOM、箱体/电源/支架/抱箍/控制箱价目、收口结构）+ 计价/报价单 Skill。"
            "计价须按本项目重算收口分项（禁止样例每平米收口×招标面积）；报价单用本项目尺寸填全表头并输出三档总价；"
            "支架/线材/接收卡/控制系统/工控机/69/750/1.03/0.68 一律照 skill，禁止去翻原表或猜数。"
            "用户若要求 Word/PDF，报价单岗优先用平台 docx/pdf Skill，不够则在工作区写代码转换。"
            "无 MCP。不定责，不盖章，不建单。"
        ),
        "start_prompt": (
            "以当前任务附件为准跑完契约。附件须含招标 PDF、规格单价表、核算口径表；无大模组核算原表。"
            "解析通读整本招标抽报价字段（自行定位清单与技术条款，勿假定固定附件编号）；"
            "点间距有毫米距须抄录并注出处，禁止无毫米时乱标用户指定。"
            "复核对照 PDF 全面核对。"
            "读表登记规格单价表与核算口径（两辅材、箱体、电源、支架、抱箍、控制箱、每平米收口）。"
            "计价按 chuangdi-quote-price：本项目重算模组（规格宽高+面积，除不尽向下取整）、箱体元/㎡、电源（有维护定额或 question）、BOM 辅材包材；"
            "招标技术条款已有毫米点间距直接用；仅无毫米距才 question。禁止样例×面积。"
            "第一次提交作业单必须一次列入全部六个执行岗。依赖以契约为准，不要改、不要漏。"
            "每一波对照验收标准通过即可，不要打回。各岗只交自己契约内的文件。"
            "交付物指代招标内容用页码+招标序号+设备名称；正文无工具名、参数名、置信度。"
            "形态不清或无毫米点间距时 question，且必须附建议项（价表档/形态表等），不默认代选。"
            "报价单：仅需报价；全表头；平方单价来自 04；形态/控制系统/写死常数照 sheet skill；"
            "必出三档综合报价总价；立柱钢构未计入清单；禁止用非本项目样例尺寸；禁止去翻原表。"
            "任务说明若要求 Word 或 PDF：优先 skill docx/pdf；失败则工作区写代码生成。"
        ),
        "visibility": "tenant",
        "mode": "pipeline",
        "accept_criteria": "\n".join(
            [
                "1. 01-解析.md：按 chuangdi-quote-scope 分类；需报价字段齐全；点间距毫米距注明出处（招标技术条款有则抄录）；"
                "不报价为名单式；含嵌入式屏的预告标志进需报价；无工具名。该岗只有这一个文件。",
                "2. 02-复核.md 按范围 skill 与页码核对分类与需报价字段；招标技术条款已有毫米距却标未给出则退回；"
                "误分类或非本品展开全字段则退回。该岗只有这一个文件。",
                "3. 03-读表.md 写明规格单价表与核算口径表（两辅材、箱体、电源、支架、抱箍、控制箱、每平米收口）的文件名、工作表、列；"
                "不算金额。该岗只有这一个文件。",
                "4. 04-计价.md 仅用复核通过的条目；本项目重算收口分项（模组块数由规格宽高推算并向下取整；箱体元/㎡；电源有定额或 question；BOM 辅材包材）；"
                "禁止样例收口×面积；仅无毫米点间距须先 question；招标技术条款已有毫米距不得标用户指定。该岗只有这一个文件。",
                "5. 05-物料核对.md 对照附件规格单价表核大件；一致写规格，否则只列候选；无单价。该岗只有这一个文件。",
                "6. 报价单.md：仅需报价；常规产品全表头；本项目尺寸；平方单价来自 04；支架/线材/接收卡/控制系统按 sheet skill；"
                "写死常数照 skill；必含三档综合报价总价 Σ(报价×数量)；未计入钢构清单；含出处页码；无工具名；未去翻原表。"
                "若任务要求 Word/PDF，另交 报价单.docx / 报价单.pdf。该岗不交其它岗位文件。",
                "7. 任一岗位出现其他岗位的文件，本岗验收不通过。",
            ]
        ),
        "max_rounds": 3,
        "approval_policy": {"budget": 3, "supervisor_preauth": [], "auto_reuse": True},
        "enabled": True,
        "members": [
            {
                "role_id": role_ids["lead"],
                "duty": "负责报价链审计口径，不改单据",
                "is_supervisor": True,
            },
            {
                "role_id": role_ids["parse"],
                "duty": "第 1 环 - 清单解析",
                "order": 1,
                "output_contract": "01-解析.md：需报价/不报价条目；标题含页码+招标序号+名称",
                "produces": ["01-解析.md"],
            },
            {
                "role_id": role_ids["check"],
                "duty": "第 2 环 - 原文复核（全面）",
                "order": 2,
                "input_contract": "上游 01-解析.md 与任务 PDF",
                "output_contract": "02-复核.md：按页码全面通过或退回；不改抄录",
                "produces": ["02-复核.md"],
            },
            {
                "role_id": role_ids["book"],
                "duty": "第 3 环 - 读表",
                "order": 3,
                "input_contract": "上游复核与任务 xlsx",
                "output_contract": "03-读表.md：规格单价表 + 核算口径 BOM/价目含控制箱/收口结构；不算金额",
                "produces": ["03-读表.md"],
            },
            {
                "role_id": role_ids["price"],
                "duty": "第 4 环 - 本项目收口重算",
                "order": 4,
                "input_contract": "上游读表与复核抄录；三件套；无毫米距/缺电源定额/缺形态时问用户",
                "output_contract": "04-计价.md：本项目分项收口；向下取整；BOM；控制箱可预列；禁止样例×面积",
                "produces": ["04-计价.md"],
            },
            {
                "role_id": role_ids["mat"],
                "duty": "第 5 环 - 物料核对",
                "order": 5,
                "input_contract": "上游计价品名规格与附件规格单价表",
                "output_contract": "05-物料核对.md：价表规格或候选；无单价",
                "produces": ["05-物料核对.md"],
            },
            {
                "role_id": role_ids["sheet"],
                "duty": "第 6 环 - 正式报价单（可按需转 Word/PDF）",
                "order": 6,
                "input_contract": "上游 01–05 与招标项目信息；任务说明中的导出格式要求",
                "output_contract": "报价单.md：仅需报价；全表头；三档总价；形态/控制系统/写死常数照 sheet skill；按需 docx/pdf",
                "produces": ["报价单.md"],
            },
        ],
    }


def _worker(
    key: str,
    name: str,
    description: str,
    persona: str,
    skill: str,
    extra_skills: list[str] | None = None,
    shell: bool = False,
    question: bool = False,
) -> dict:
    """执行岗：读附件、写交付物、加载 Skill；默认不委派、不跑 shell、无 MCP。"""
    skills = [skill, *(extra_skills or [])]
    caps = [
        "tool:read",
        "tool:grep",
        "tool:glob",
        "tool:skill",
        *[f"skill:{s}" for s in skills],
    ]
    if question:
        caps.append("tool:question")
    rules = [
        *READ,
        *PERSIST,
        *SKILL_ALLOW,
        *(SHELL if shell else NO_SHELL),
        *NO_NET,
        *NO_DELEGATE,
    ]
    if question:
        rules.append({"permission": "question", "pattern": "*", "action": "allow"})
    return {
        "key": key,
        "role": {
            "name": name,
            "description": description,
            "persona": persona,
            "capabilities": caps,
            "permissions": rules,
            "approval_policy": ROLE_POLICY,
            "memory_scope": "session",
            "enabled": True,
        },
    }


def _lead(key: str, name: str, description: str, persona: str) -> dict:
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


ROLES = [
    _lead(
        "lead",
        "创迪-报价链主管",
        "报价链负责人（不在接力环上，不改单据）",
        (
            "你负责「创迪-情报板报价」流水线审计。"
            "你不亲自解析、不算价、不改单据。确保六环按序完成并产出正式报价单。"
            "禁止审批通过、用印、建单。产出用简体中文。"
        ),
    ),
    _worker(
        "parse",
        "创迪-清单解析员",
        "第 1 环：按产品范围与销售字段通读招标抽取",
        (
            f"你是清单解析员。加载 skill {SCOPE_SKILL}、{PARSE_SKILL} 与 {RUNBOOK}。"
            "先按产品范围 skill 判定需报价/本次不报价，再抽字段。"
            "含嵌入式显示屏的预告标志（如停车位入口预告标志）进需报价并归并嵌入式/信息发布；"
            "信号灯、雾灯、车道指示器、电光/疏散标志、弱电系统、纯结构件、纯静态标志进不报价名单。"
            "需报价条目标题写成「第×页 · 招标序号 N · 设备名称」。范围含糊则 question。"
            "点间距：通读整本招标技术条款（章节因标书而异）；有毫米距须抄录并注出处；仅分辨率或无毫米距写「招标未给出毫米点间距」。"
            "只写入 01-解析.md。清单名称保持招标原文。禁止创建其他岗位的文件。"
            "禁止猜测。文档不写工具名。产出用简体中文。"
        ),
        PARSE_SKILL,
        extra_skills=[SCOPE_SKILL],
        question=True,
    ),
    _worker(
        "check",
        "创迪-原文复核员",
        "第 2 环：对照 PDF 全面复核解析输出",
        (
            f"你是原文复核员。加载 skill {SCOPE_SKILL}、{REVIEW_SKILL} 与 {RUNBOOK}。"
            "按产品范围 skill 核对分类；读上游 01-解析，按页码核对需报价字段；"
            "非本品误入需报价或展开全套报价字段须退回；含嵌入式屏的预告标志不得误入不报价。"
            "本次不报价只核分类与理由，不核报价字段。"
            "只写入 02-复核.md。不改抄录数字，不算金额。禁止创建其他岗位的文件。"
            "文档不写工具名。产出用简体中文。"
        ),
        REVIEW_SKILL,
        extra_skills=[SCOPE_SKILL],
    ),
    _worker(
        "book",
        "创迪-读表员",
        "第 3 环：登记三件套中的两张表（含 BOM）",
        (
            f"你是读表员。加载 skill {RUNBOOK}。"
            "只读任务附件里的规格单价表与核算口径表。"
            "只写入 03-读表.md：两份文件名；规格单价各表与列、模组行数；"
            "核算口径必须点名 压铸铝辅材、铁箱辅材、箱体、电源、支架、安装抱箍和螺钉、控制箱、每平米收口 及关键列。"
            "禁止创建其他岗位的文件。不算金额。若见供应商表则停止并退回。文档不写工具名。产出用简体中文。"
        ),
        RUNBOOK,
    ),
    _worker(
        "price",
        "创迪-计价员",
        "第 4 环：本项目收口重算",
        (
            f"你是计价员。加载 skill {PRICE_SKILL} 与 {RUNBOOK}。"
            "按计价 skill 对本项目重算收口分项，写入 04-计价.md（演算底稿，非对外报价单）。"
            "禁止样例每平米收口×招标面积。模组块数=面积÷单块面积后向下取整；箱体用核算口径箱体元/㎡×面积；"
            "电源只数用核算口径维护定额或 question；辅材包材来自 BOM（汇总空则滚明细）。"
            "点间距：招标技术条款/抄录已有毫米距直接用，禁止标用户指定；仅无毫米距、电源无定额、形态不清时用 question。"
            "支架/抱箍/控制系统与报价单 skill 一致：控制系统每套（控制箱汇总不按㎡折）；抱箍与支架分列；"
            "双幅先 question 是否×屏数；立柱钢构未计列明。数量除不尽向下取整并备注。"
            "只写入 04-计价.md。禁止创建其他岗位的文件。文档不写工具名。产出用简体中文。"
        ),
        PRICE_SKILL,
        question=True,
    ),
    _worker(
        "mat",
        "创迪-物料核对员",
        "第 5 环：对照附件价表核对规格",
        (
            f"你是物料核对员。加载 skill {RUNBOOK}。"
            "只读任务附件中的规格单价表，对照上游计价品名与规格。"
            "只写入 05-物料核对.md。禁止创建其他岗位的文件。"
            "一致写价表规格标识；不能唯一命中时只列候选，禁止把第一个候选写成已对应，禁止写单价。"
            "文档不写工具名。产出用简体中文。"
        ),
        RUNBOOK,
    ),
    _worker(
        "sheet",
        "创迪-报价单员",
        "第 6 环：正式报价单；按用户要求转 Word/PDF",
        (
            f"你是报价单员。加载 skill {SHEET_SKILL} 与 {RUNBOOK}。"
            "写出正式报价单.md：仅需报价条目；常规产品全表头；长宽用本项目抄录。"
            "平方单价来自 04；支架/线材/接收卡/控制系统按 sheet skill；"
            "04 与本单支架/抱箍/控制系统数字必须一致；控制系统每套（汇总不÷10）；抱箍勿并进支架单价；"
            "工控机 2580+200+200、接收卡 69/750、×1.03、比例 0.68 照 skill；必出三档综合报价总价 Σ(报价×数量)；"
            "未计入钢构清单；招标技术条款已有毫米点间距不得写用户指定；禁止去翻原表或猜公式。"
            "禁止用非本项目样例长宽；禁止写入本次不报价名单。"
            f"若任务说明要求 Word 或 .docx：优先加载 skill {DOCX_SKILL} 生成 报价单.docx；"
            f"若任务说明要求 PDF：优先加载 skill {PDF_SKILL} 生成 报价单.pdf（中文按 pdf skill 配 CJK 字体）。"
            "Skill 失败则工作区写代码，内容与 md 一致。未要求则不导出。"
            "不定责、不盖章、不建单。文档不写工具名。产出用简体中文。"
        ),
        SHEET_SKILL,
        extra_skills=[PDF_SKILL, DOCX_SKILL],
        shell=True,
    ),
]


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
        "  python3 inject_chuangdi_quote.py --tenant <租户>",
        file=sys.stderr,
    )
    raise SystemExit(1)


class Client:
    """控制台 HTTP。租户头把 Skill、角色、协作写进指定租户。"""

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


def ensure_skills(client: Client) -> None:
    root = LOCAL_SKILLS
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
    parser = argparse.ArgumentParser(description="Inject Chuangdi quote team (skills only, no MCP)")
    parser.add_argument("--base", default=os.environ.get("RUNTIME_BASE_URL", "http://127.0.0.1:4096"))
    parser.add_argument("--tenant", default=os.environ.get("AGENTFORGE_TENANT", ""))
    parser.add_argument("--role", default=os.environ.get("AGENTFORGE_ROLE", "admin"))
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

    if not args.skip_skills:
        ensure_skills(client)

    print("==> bundle quote (no MCP)")
    role_ids = upsert_roles(client, ROLES)
    upsert_team(client, team_quote(role_ids))
    print(f"完成 tenant={tenant} skills-only")


if __name__ == "__main__":
    main()
