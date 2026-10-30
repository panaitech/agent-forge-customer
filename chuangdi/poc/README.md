# 报价落地（创迪）

主路径：**Agent Forge** 协作「创迪-情报板报价」。见 [业务流程.md](业务流程.md)。

## 目录

| 路径 | 作用 |
| --- | --- |
| `scripts/` | 注入、Skill |
| `整理原表.py` / `seed_demo.py` / `book.py` | 本机生成 `../数据/` 后上传附件 |
| `run.py` 等 | 价表 selfcheck |

## Forge 一次任务

1. `cd scripts && python3 inject_chuangdi_quote.py --tenant '...' --base http://127.0.0.1:4096`  
2. 附件：招标 PDF + 规格单价表 + 核算口径表  
3. 可选：任务说明写要 Word/PDF，或补充排除范围  
4. 解析岗通读招标自动出 `01-解析.md`；最终 `报价单.md`（及按需 docx/pdf）

租户需安装预置 Skill `docx`、`pdf`。
