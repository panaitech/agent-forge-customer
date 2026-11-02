# 雨中情 WeCom Bridge（企微对接服务）

独立进程，夹在企业微信自建应用与 Agent Forge 之间，对应设计方案 **S0/S1（合同录入完整链路）**：

- 回调验签 / 解密（Token + EncodingAESKey）
- 身份链接 `wecom_identity_link`（规则：`wecom:{corp_id}:{userid}`）
- 机器账号 **启动「雨中情-合同录入」pipeline 协作**（`POST /team/:id/run`）
- L0 受理 → L1 阶段轮询 → HITL「去确认」深链 → 终态通知

## 目录

```text
wecom-bridge/
├── app/
│   ├── main.py              # FastAPI：/wecom/callback、/confirm、/healthz
│   ├── config.py
│   ├── crypto/wecom_crypt.py
│   ├── identity/            # owner 规则 + SQLite 链接表
│   ├── wecom/               # 企微 API 与 XML 解析
│   ├── forge/               # Agent Forge 客户端（team.run / approval）
│   ├── ticket/              # 确认深链
│   ├── messages/            # L0/L1 文案
│   └── pipeline/            # inbound + run 进度监视
├── scripts/
│   ├── import_members.py    # S0 过渡批量导入
│   └── sync_contacts.py     # 通讯录同步
├── tests/
├── requirements.txt
└── .env                     # 本地配置（勿提交）
```

## 配置

```bash
cp ../config/bridge.example.env .env
# 编辑 WECOM_*、AF_*、TICKET_SECRET
```

企业级绑定：`WECOM_CORP_ID` + `AF_TENANT_ID` + 默认角色 + 机器账号。成员映射由规则与同步生成。

**录入协作前置**：在目标租户 inject「雨中情-合同录入」（见 `docs/poc/合同录入与初审演示方案.md`），并配置：

```bash
# 二选一：名称（默认）或显式 team id
AF_INTAKE_TEAM_NAME=雨中情-合同录入
# AF_INTAKE_TEAM_ID=tm_xxxxxxxx
```

Runtime 机器账号须 `AGENTFORGE_IDENTITY_MAP` 含 `"delegate":true`，否则协作 run 的 owner 不会落到业务员。

## 安装与运行

### A. Docker（推荐：本地 / 腾讯云）

详见 [`docker/README.md`](docker/README.md)。

```bash
cd wecom-bridge
cp ../config/bridge.example.env .env
# 本机
bash docker/local/deploy.sh up
# 腾讯云
# CLOUD_HOST=<IP> bash docker/tencent/deploy.sh
```

### B. 裸进程（开发调试）

```bash
cd wecom-bridge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# 联调可先开 dry-run
export DRY_RUN_FORGE=true DRY_RUN_WECOM_SEND=true
PYTHONPATH=. python -m app
# 或：PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8787
```

企微回调填写：`https://<公网域名>/wecom/callback`

## 身份导入

```bash
# 过渡：可见范围导出后
PYTHONPATH=. python scripts/import_members.py --file members.txt

# 主路径：通讯录同步
PYTHONPATH=. python scripts/sync_contacts.py --department-id 1
```

## 测试

```bash
cd wecom-bridge
pip install -r requirements-dev.txt
PYTHONPATH=. python -m pytest tests -q
```

## 与方案章节对照

| 方案 | 代码 |
| --- | --- |
| §3.3 owner 规则 | `app/identity/owner.py` |
| §4 链接表 | `app/identity/store.py` |
| §6.2 验签解密 | `app/crypto/wecom_crypt.py` |
| §6.4 机器账号 | `app/forge/client.py`（须 Runtime `IDENTITY_MAP.delegate=true`） |
| §6.5 ticket | `app/ticket/token.py` → `/confirm` 跳转 `/teams/runs/:runID` |
| P0-A / S1 录入 | `inbound` 启动 team.run + `monitor` 轮询 stage/HITL |
| §7.1 入站流水线 | `app/pipeline/inbound.py`（幂等 + 附件 + 启动录入协作） |

## 生产注意

1. Runtime：`AGENTFORGE_IDENTITY_MAP` 为 Bridge 用户配置 `"delegate":true`，否则会话 owner 不会落到 `wecom:{corp}:{userid}`（创建后会报 OwnerMismatch）。  
2. `BRIDGE_ADMIN_TOKEN` 为空则管理导入 API 404；优先用 `scripts/import_members.py`。  
3. `/confirm` 仍为演示级跳转，生产需 SSO/企微 OAuth。  
4. 可将 `IDENTITY_AUTO_PROVISION=false`，仅允许通讯录同步/导入过的成员。  
