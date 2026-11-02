# 雨中情（yuzq）交付目录

本目录承载雨中情合同助手相关方案落地工件：设计文档、企微对接服务（WeCom Bridge）、运维清单与配置样例。

## 目录结构

```text
yuzq/
├── README.md
├── docs/                         # 方案与需求（既有）
│   ├── 方案/                     # 入口落地、身份/Bridge、交互设计
│   ├── 需求整理/
│   ├── poc/                      # 控制台协作演示说明
│   └── v1|v2|v3/                 # 历次方案与注入脚本
├── wecom-bridge/                 # S0 企微对接服务实现
│   ├── app/                      # FastAPI 服务
│   ├── docker/                   # 本机 + 腾讯云 Docker 部署
│   ├── scripts/                  # 通讯录导入/同步
│   ├── tests/
│   └── README.md
├── config/                       # 配置样例（无密钥）
└── ops/                          # 上线检查与文案模板
```

## 与方案的对应关系

| 方案文档 | 落地位置 |
| --- | --- |
| `docs/方案/企微身份映射与对接服务设计方案.md` | `wecom-bridge/`（验签解密、身份链接、机器账号调 AF、ticket） |
| `docs/方案/企微合同助手用户场景与交互设计方案.md` | `wecom-bridge/app/messages/`、`ops/文案模板.md` |
| `docs/方案/企微入口与P0落地实施方案.md` | 本目录整体；P0-A/B 协作仍见 `docs/v3` / `docs/poc` |

## 快速开始（Bridge）

见 [`wecom-bridge/README.md`](wecom-bridge/README.md)。
