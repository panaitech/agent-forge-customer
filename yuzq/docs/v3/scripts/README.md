# 雨中情合同演示 v3：评审流水线注入

向**指定租户**注入两条协作，并注册租户私有 `yuzhongqing-poc-contract` MCP / Skill。  
其它租户开箱不可见（**未**写入 Runtime 默认 `agentforge.jsonc`）。

方案正文在上一级。v2 的录入 + 四环初审脚本在 `../../v2/scripts/`。  
本目录的 Skill 只从这里读取，不覆盖 runtime 里 v2 的作业标准。

评审语料在 runtime `demos/yuzhongqing-contract/v3-corpus/`（技术、商务、法务，以及结算、签收、栏目提示）。MCP 默认读这一份。旧规则在同包 `v2-corpus/`，需要时设 `YUZHONGQING_CORPUS_DIR=v2-corpus`。物料别名表 `materials.json` 仍在 `v2-corpus`，不随检索目录切换。

MCP 启动命令（相对容器内 `packages/opencode`）：

```text
bun run ../../demos/yuzhongqing-contract/mcp/contract-server.ts
```

`search_rule` 没有命中的技术参数、标准号、法条，仍写「无法判断」。

---

## 注入

```bash
cd /path/to/agent-forge-docs/11-企业客户方案/雨中情/v3/scripts
export AGENTFORGE_USER='...'
export AGENTFORGE_PASSWORD='...'
python3 inject_yuzhongqing_demos.py --tenant '<租户>' --base http://127.0.0.1:4196
```

只注一条：

```bash
python3 inject_yuzhongqing_demos.py --tenant '<租户>' --only intake
python3 inject_yuzhongqing_demos.py --tenant '<租户>' --only review
```

本机 OCR 仍用 v2 目录里的脚本：`../../v2/scripts/ocr/`。

## 注入结果

| 协作名 | 模式 | 人工闸门 |
| --- | --- | --- |
| 雨中情-合同录入 | pipeline | `upsert_contract_draft` |
| 雨中情-合同评审 | pipeline | `upsert_review_card` |

默认案例号 `YZQ-2026-003`。数据为演示虚构。「一天 200 单」不在本脚本里当作验收指标。

| 角色 | 协作 |
| --- | --- |
| 雨中情-合同受理主管及录入四环 | 录入，与 v2 相同 |
| 雨中情-评审链主管 | 评审链审计，不改单据 |
| 雨中情-基础初审员 | 产品、价格、交期、三单、签收；数字只引用规则工具 |
| 雨中情-技术标注员 / 商务标注员 / 法务提示员 | 检索条目并引用；未覆盖写无法判断 |
| 雨中情-分层卡片员 | 同一张卡按环节追加，写回须人批 |
| 雨中情-执行提醒员 | 发货排产、补充协议、退换货只提醒，不写回 |
