# 创迪报价：Agent Forge 注入（无 MCP）

## 任务输入

| 内容 | 方式 |
| --- | --- |
| 招标书、规格单价表、核算口径表 | 附件。招标书可以是 PDF，也可以是上一轮解析后的文档 |
| Word / PDF（可选） | 任务说明写明 |

解析岗通读招标书自动抽取。任务附件为招标书 + 规格单价表 + 核算口径表（含控制箱；**不上传**大模组核算原表）。招标书不必是 PDF。  
读表/计价落实三件套；`04` 本项目重算并预列支架/抱箍/控制系统；报价单**抄 04**（含抱箍三列）+ 写死常数算总价；禁止报价单岗重算形态；禁止去翻原表。  
产品范围见 skill `chuangdi-quote-scope`。招标技术条款有毫米点间距须抄录（章节因标书而异）；仅无毫米距或形态/电源定额不清时 question（须附建议项）。

## 注入

```bash
export AGENTFORGE_USER='...'
export AGENTFORGE_PASSWORD='...'
python3 inject_chuangdi_quote.py --tenant '<租户>' --base http://127.0.0.1:4096
```

请先安装官方预置 Skill：`docx`、`pdf`。
