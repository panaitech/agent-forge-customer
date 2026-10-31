# 创迪报价：Agent Forge 注入（无 MCP）

## 任务输入

| 内容 | 方式 |
| --- | --- |
| 招标 PDF、规格单价表、核算口径表 | 附件 |
| Word / PDF（可选） | 任务说明写明 |

解析岗通读招标书自动抽取。任务附件为招标 PDF + 规格单价表 + 核算口径表（**不上传**大模组核算原表）。  
读表/计价落实三件套；`04` 本项目重算收口（禁止样例×面积）；报价单全表头；支架/线材/接收卡与写死常数照 skill，禁止去翻原表。  
产品范围见 skill `chuangdi-quote-scope`。招标未给点间距或形态/电源定额不清时 question。

## 注入

```bash
export AGENTFORGE_USER='...'
export AGENTFORGE_PASSWORD='...'
python3 inject_chuangdi_quote.py --tenant '<租户>' --base http://127.0.0.1:4096
```

请先安装官方预置 Skill：`docx`、`pdf`。
