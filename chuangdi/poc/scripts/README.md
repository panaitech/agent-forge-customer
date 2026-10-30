# 创迪报价：Agent Forge 注入（无 MCP）

## 任务输入

| 内容 | 方式 |
| --- | --- |
| 招标 PDF、规格单价表、核算口径表 | 附件 |
| Word / PDF（可选） | 任务说明写明 |

解析岗通读招标书自动抽取。读表/计价须落实三件套：规格单价表 + 核算口径 BOM + 公式链 Skill。

## 注入

```bash
export AGENTFORGE_USER='...'
export AGENTFORGE_PASSWORD='...'
python3 inject_chuangdi_quote.py --tenant '<租户>' --base http://127.0.0.1:4096
```

请先安装官方预置 Skill：`docx`、`pdf`。
