# 雨中情合同演示：协作注入与本机 OCR

向**指定租户**注入两条业务协作，并注册租户私有 `yuzhongqing-poc-contract` MCP / Skill。  
其它租户开箱不可见（**未**写入 Runtime 默认 `agentforge.jsonc`）。

MCP 进程、三份虚构案例和语料在 runtime：`demos/yuzhongqing-contract/`。  
本目录负责按租户注入，并带一份 Skill 副本；runtime 里已有 `skills/*/SKILL.md` 时，注入改读 runtime。

MCP 启动命令（相对容器内 `packages/opencode`）：

```text
bun run ../../demos/yuzhongqing-contract/mcp/contract-server.ts
```

---

## 1. 注入协作

Runtime 起来之后：

```bash
cd /path/to/agent-forge-docs/11-企业客户方案/雨中情/v2/scripts
export AGENTFORGE_USER='...'
export AGENTFORGE_PASSWORD='...'
python3 inject_yuzhongqing_demos.py --tenant '<租户>' --base http://127.0.0.1:4196
```

只注一条：

```bash
python3 inject_yuzhongqing_demos.py --tenant '<租户>' --base http://127.0.0.1:4196 --only intake
python3 inject_yuzhongqing_demos.py --tenant '<租户>' --base http://127.0.0.1:4196 --only review
```

Skill 优先读 runtime `demos/yuzhongqing-contract/skills/`。该目录还没有文件时，才读本目录 `skills/`。

官方镜像里 cwd 异常时再覆盖 MCP 脚本路径：

```bash
export YUZHONGQING_MCP_SCRIPT=/app/demos/yuzhongqing-contract/mcp/contract-server.ts
```

经网关注入时 `--base` 用 `https://<主机>/console/api`，不要打到门户根路径 `/api`。

## 注入结果

| 协作名 | 模式 | 人工闸门 |
| --- | --- | --- |
| 雨中情-合同录入 | pipeline | `upsert_contract_draft` |
| 雨中情-合同初审 | pipeline | `upsert_review_card` |

默认案例号 `YZQ-2026-003`（主演示异常单）。`YZQ-2026-001` 干净单、`YZQ-2026-002` 叫法不一致，改 `start_prompt` 里的案例号即可。数据为演示虚构。

| 角色 | 协作 |
| --- | --- |
| 雨中情-合同受理主管 | 录入，只审计，不改单据 |
| 雨中情-收件识别员 / 要素提取员 / 清单匹配员 / 缺件追问员 | 录入四环 |
| 雨中情-区域初审主管 | 初审，只审计，不改单据 |
| 雨中情-三单比对员 / 结算复算员 / 签收核对员 / 评审卡片员 | 初审四环 |

MCP 名 `yuzhongqing-poc-contract`。读：`list_cases`、`get_case`、`get_quote`、`get_receipt`、`search_material`、`search_rule`、`ocr_attachment`。规则：`match_lines`、`check_payment`、`check_amounts`、`check_delivery`。写（须人批）：`upsert_contract_draft`、`upsert_review_card`。

## 2. 本机 OCR

脚本从 math-pocket 拷出，放在 `ocr/`。推理代码与权重仍在原仓库，不打进 runtime 镜像。

```bash
# 终端 A：VL 推理（Docker，默认 127.0.0.1:8022）
bash ocr/run_vllm.sh

# 终端 B：OCR HTTP（默认 127.0.0.1:18088，避开本机 Airflow 的 8088）
bash ocr/start_ocr_inference.sh
```

健康检查：`GET http://127.0.0.1:18088/health`。  
上传接口：`POST http://127.0.0.1:18088/ocr/parse-question-image-upload`。

`start_ocr_inference.sh` 的工作目录默认是  
`/home/pan/work/math/github/math-pocket/services/ocr-inference`。  
换机器时设置 `MATH_POCKET_ROOT` 或 `OCR_SERVICE_DIR`。

`ocr/wait-inference-health.sh` 提供 `wait_vllm_health` / `wait_ocr_health`，给启动脚本 `source` 用。
