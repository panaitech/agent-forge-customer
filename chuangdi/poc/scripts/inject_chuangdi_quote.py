# 职责：向指定租户注入创迪情报板报价协作与作业 Skill（无 MCP）。
# 不改 Runtime 默认 agentforge.jsonc，其它租户开箱看不见。
# 形态对齐雨中情 v3 的 Skill/角色/协作注入，但不注册 MCP。
"""创迪报价注入（附件 + Skill）。

资产：
  - Skill：本目录 skills/ 整包（SKILL.md 与 scripts/ 等附属文件）
  - 本脚本只对 --tenant 写入 Skill / 建角色 / 建协作

一条协作（主管监督制，成员 needs 决定挂载）：
  创迪-情报板报价

任务须上传招标书、规格单价表、核算口径表。招标书可以是 PDF，也可以是上一轮解析后的文档。
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
    """解析 → 复核 → 读表 → 计价 → 正式报价单。"""
    return {
        "name": "创迪-情报板报价",
        "description": (
            "场景：任务已上传招标书、规格单价表与核算口径表（不上传大模组核算原表）。"
            "三件套：规格单价表 + 核算口径表（BOM、箱体/电源/支架/抱箍/控制箱价目、收口结构）+ 计价/报价单 Skill。"
            "计价须按本项目重算收口分项（禁止样例每平米收口×招标面积）；报价单用本项目尺寸填全表头并输出三档总价；"
            "支架/线材/接收卡/控制系统/工控机/69/750/1.03/0.68 一律照 skill，禁止去翻原表或猜数。"
            "用户若要求 Word/PDF，报价单岗优先用平台 docx/pdf Skill，不够则在工作区写代码转换。"
            "无 MCP。不定责，不盖章，不建单。"
        ),
        "start_prompt": (
            "按验收标准跑完这一轮。"
            "附件：招标书、规格单价表、核算口径表。不要大模组核算原表。"
            "招标书可以是 PDF，也可以是上一轮解析后的文档。"
            "任务说明若要求 Word 或 PDF，由报价单岗导出。"
        ),
        "visibility": "tenant",
        "mode": "supervisor",
        "accept_criteria": "\n".join(
            [
                "1. 01-解析.md：按 chuangdi-quote-scope 分类；需报价字段齐全；每条附清单行与所用技术条款的原文片段；文首有项目名称与招标编号；"
                "点间距毫米距注明出处（招标技术条款有则抄录）；不报价为名单式；含嵌入式屏的预告标志进需报价；无工具名。该岗只有这一个文件。",
                "2. 02-复核.md 只对照 01 的原文片段核对分类与字段，不打开招标书；片段有毫米距却标未给出、或缺片段、片段中没有的数被写成有数，则退回。"
                "误分类或非本品展开全字段则退回。该岗只有这一个文件。",
                "3. 03-读表.md 按作业标准写成结构化表：规格模组行与箱体标识、两辅材明细与汇总、箱体元/㎡、电源、支架、抱箍、控制箱汇总、常规电源数量；"
                "数字与表内一致；不算本项目金额。该岗只有这一个文件。",
                "4. 04-计价.md 只读 01、02、03，不打开表格；面积=长×高×屏数；金额与三档总价全部来自计价脚本；仅用复核通过的条目；禁止样例收口×面积；03 未登记的单价写待确认。"
                "双幅不再×屏数；未写面别按单面；电源无维护值按 2 只/㎡；支架永远按形态公式算，只有交安已供整套钢构才为 0；含立柱、含支座、附着既有的本体进未计入钢构，支架抱箍照算。这些默认写进备注即通过，不得为此打回或再问。"
                "支架数量只按形态公式（悬臂、车道、服务区=长×高；天棚、门架=长+2；洞内=(长÷2+1)×1；小型=长+1），小数向下取整；价目单位套/平方只在备注，不得改数量算法。"
                "线材、接收卡按形态公式；控制系统按每套底数加形态加价。被打回后只改点名序号，未点名的数保持不动。该岗只有这一个文件。",
                "5. 报价单.md：仅需报价；全表头；平方单价、屏体合计、支架/抱箍/控制系统/线材/接收卡、工控机、接收卡合计、三档综合价格与报价、三档总价全部抄 04（与 04 同数字），禁止重算；"
                "含抱箍数量/单价/合计列；未计入钢构清单；含出处页码；无工具名。"
                "若任务要求 Word/PDF，另交 报价单.docx / 报价单.pdf。该岗不交其它岗位文件。",
                "6. 任一岗位出现其他岗位的文件，本岗验收不通过。",
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
                "duty": "第 1 波 - 清单解析",
                "output_contract": "01-解析.md：需报价/不报价条目；每条附原文片段；文首含项目名称与招标编号",
                "produces": ["01-解析.md"],
            },
            {
                "role_id": role_ids["check"],
                "duty": "第 2 波 - 片段复核",
                "needs": [role_ids["parse"]],
                "input_contract": "只读上游 01-解析.md 中的字段与原文片段，不打开招标书",
                "output_contract": "02-复核.md：对照片段通过或退回；不改抄录",
                "produces": ["02-复核.md"],
            },
            {
                "role_id": role_ids["book"],
                "duty": "第 1 波 - 读表",
                "input_contract": "任务附件中的规格单价表与核算口径表，摘成结构化价目",
                "output_contract": "03-读表.md：模组行、箱体标识、两辅材、箱体元/㎡、电源、支架、抱箍、控制箱汇总、常规电源数量；不算本项目金额",
                "produces": ["03-读表.md"],
            },
            {
                "role_id": role_ids["price"],
                "duty": "第 3 波 - 本项目收口重算",
                "needs": [role_ids["parse"], role_ids["check"], role_ids["book"]],
                "input_contract": "只读上游 01-解析、02-复核、03-读表；禁止打开表格；无毫米距/缺电源定额/缺形态时问用户",
                "output_contract": "04-计价.md：本项目分项收口；向下取整；BOM；控制箱可预列；禁止样例×面积",
                "produces": ["04-计价.md"],
            },
            {
                "role_id": role_ids["sheet"],
                "duty": "第 4 波 - 正式报价单（可按需转 Word/PDF）",
                "needs": [
                    role_ids["parse"],
                    role_ids["check"],
                    role_ids["price"],
                ],
                "input_contract": "上游 01-解析、02-复核、04-计价与招标项目信息；任务说明中的导出格式要求",
                "output_contract": "报价单.md：抄04形态金额；抱箍三列；三档总价；写死常数；按需 docx/pdf",
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
            "你不亲自解析、不算价、不改单据。按波次验收并产出正式报价单。第 1 波清单解析与读表并行。"
            "禁止调用 question。04 备注里已经写明的口径不要再问用户，也不要打回让计价员重问。"
            "计价岗打回只写补丁清单：招标序号、字段、现行值、应用公式，并写明未点名的数保持不动。"
            "禁止要求计价岗按套或按面积重算支架。禁止审批通过、用印、建单。产出用简体中文。"
        ),
    ),
    _worker(
        "parse",
        "创迪-清单解析员",
        "第 1 波：按产品范围与销售字段通读招标抽取，与读表并行",
        (
            f"你是清单解析员。加载 skill {SCOPE_SKILL}、{PARSE_SKILL} 与 {RUNBOOK}。"
            "先按产品范围 skill 判定需报价/本次不报价，再抽字段。"
            "含嵌入式显示屏的预告标志（如停车位入口预告标志）进需报价并归并嵌入式/信息发布；"
            "信号灯、雾灯、车道指示器、电光/疏散标志、弱电系统、纯结构件、纯静态标志进不报价名单。"
            "需报价条目标题写成「第×页 · 招标序号 N · 设备名称」。每条摘录清单行原文，用到的技术条款另附句子和页码。不抄整章。"
            "文首写项目名称和招标编号，未载明则写招标文件未载明。"
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
        "第 2 波：只对照 01 的原文片段复核，不打开招标书",
        (
            f"你是原文复核员。加载 skill {SCOPE_SKILL}、{REVIEW_SKILL} 与 {RUNBOOK}。"
            "按产品范围 skill 核对分类。只读上游 01-解析，禁止打开招标书。"
            "字段里的数必须出现在该条原文片段中；缺片段，或片段有毫米距却标未给出，则退回。"
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
        "第 1 波：把两张表摘成结构化价目，与清单解析并行",
        (
            f"你是读表员。加载 skill {RUNBOOK}。"
            "只读任务附件里的规格单价表与核算口径表，按作业标准把要用的行写成 03-读表.md。"
            "必须有：模组数据行（每个点间距选一行标「默认」，供计价岗未定配比时取用）、箱体规格标识、压铸铝辅材与铁箱辅材的明细和汇总、箱体元/㎡、电源、支架、抱箍、控制箱汇总、常规电源数量。"
            "数字与表内一致。汇总格空就写空。不算本项目金额。若见供应商表则只写退回。"
            "只写入 03-读表.md。禁止创建其他岗位的文件。文档不写工具名。产出用简体中文。"
        ),
        RUNBOOK,
    ),
    _worker(
        "price",
        "创迪-计价员",
        "第 3 波：本项目收口重算",
        (
            f"你是计价员。加载 skill {PRICE_SKILL} 与 {RUNBOOK}。"
            "按计价 skill 对本项目归类与选价，写 lines.json（每行=一套，面积由脚本算，禁止手填 area），用 skill 里的脚本算全部金额与三档总价，stdout 原样写入 04-计价.md。"
            "只读 01、02、03，禁止打开招标书和表格。"
            "shell 只运行 python3 <skill base>/scripts/calc.py，禁止改脚本，禁止其它命令。"
            "禁止在思考里逐行乘除。03 没有的单价写待确认，禁止回表补。禁止样例每平米收口×招标面积。"
            "双幅不乘屏数。未写面别按单面。电源无维护值按 2 只/㎡。支架永远按形态公式算；只有交安已供整套钢构才 steel=provided；含立柱/含支座/附着既有只填 body 进未计入钢构，支架抱箍照算。未写配比取 03 默认档并备注。"
            "只在全书无毫米点间距或形态对不上表时 question 一次，并把用户原话写入该条备注。"
            "建议项必须放进 question 的 options，第一项 label 以「（建议）」结尾；禁止把档位只写在题干里。"
            "被打回时只改点名的招标序号和字段，未点名的数禁止改。禁止整篇重写。"
            "只写入 04-计价.md。禁止创建其他岗位的文件。文档不写工具名。产出用简体中文。"
        ),
        PRICE_SKILL,
        question=True,
        shell=True,
    ),
    _worker(
        "sheet",
        "创迪-报价单员",
        "第 4 波：正式报价单；按用户要求转 Word/PDF",
        (
            f"你是报价单员。加载 skill {SHEET_SKILL} 与 {RUNBOOK}。"
            "写出正式报价单.md：仅需报价；全表头；长宽用本项目抄录。项目名称和招标编号抄 01 文首，禁止为此打开招标书。"
            "上游 01-解析、02-复核、04-计价已自动挂在 inputs/team/，直接按招标序号读，不要让用户选补挂。"
            "铁律：平方单价、屏体合计、大屏线材、支架数量/单价/合计、抱箍数量/单价/合计、控制系统、接收卡数量、工控机、接收卡合计、三档综合价格与报价、三档总价"
            "一律按招标序号从 04-计价原样抄入，禁止本岗重算任何金额（含 69/750/1.03/0.68）或再 question 双幅/服务区支架。"
            "工作区没有 04-计价.md 时停手说明缺文件，不要编补挂/重算/空骨架选项。"
            "明细表必须有「抱箍数量」「抱箍单价」「抱箍合计」三列（勿只写备注）；抱箍勿并进支架单价。"
            "本岗不再计算金额：工控机、接收卡×69/750、×1.03、÷0.68、三档总价全部抄 04；未计入钢构抄 04。"
            "招标已有毫米点间距不得写用户指定；禁止写入本次不报价名单；禁止去翻原表。"
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


def upload_pack(client: Client, name: str, skill_dir: Path) -> None:
    """把技能目录里 SKILL.md 以外的文本文件写入技能包（scripts/ 等）。"""
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(skill_dir).as_posix()
        # 字节码和隐藏文件不属于技能包，读成 UTF-8 会直接失败
        if rel == "SKILL.md" or path.suffix == ".pyc" or any(part.startswith(".") or part == "__pycache__" for part in path.parts):
            continue
        content = path.read_text(encoding="utf-8")
        status, saved = client.call("PUT", f"/skill/{name}/file", {"path": rel, "content": content})
        if status == 401:
            _die_auth(client.base, status)
        _must(status, saved if isinstance(saved, dict) else {"ok": True}, f"skill {name} {rel}")
        print(f"skill {name} {rel} ok")


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
        upload_pack(client, name, path.parent)
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


def drop_role(client: Client, name: str) -> None:
    """删掉协作已不再引用的角色，避免控制台还留着旧岗。"""
    status, existing = client.call("GET", "/agent")
    if status == 401:
        _die_auth(client.base, status)
    if status >= 400 or not isinstance(existing, list):
        print(f"警告：列出角色失败，未删除 {name} {status}", file=sys.stderr)
        return
    for row in existing:
        if not isinstance(row, dict) or str(row.get("name") or "") != name:
            continue
        status, _ = client.call("DELETE", f"/agent/{row['id']}")
        if status == 401:
            _die_auth(client.base, status)
        if status >= 400 and status != 404:
            print(f"警告：删除角色 {name} {status}", file=sys.stderr)
            continue
        print(f"role {name} removed")


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
    drop_role(client, "创迪-物料核对员")
    print(f"完成 tenant={tenant} skills-only")


if __name__ == "__main__":
    main()
