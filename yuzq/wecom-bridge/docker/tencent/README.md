# WeCom Bridge · 腾讯云部署

本目录提供与 Agent Forge Runtime 相同的部署模式：**本机构建镜像 → 上传轻量云 → `docker load` → compose 启动**。云端不保留源码树。

## 拓扑

```text
企微平台
  └─ HTTPS 回调 ──> 腾讯云 nginx(443)
                      └─ /wecom|/confirm|/healthz ──> 127.0.0.1:8787（Bridge 容器）
                                                      └─ host.docker.internal ──> 同机 Agent Forge
```

- Bridge 端口只绑 `127.0.0.1:8787`，不直接暴露公网。  
- `PUBLIC_BASE_URL` 必须为对外 HTTPS 域名（确认深链与企微回调一致）。  
- 生产关闭 `DRY_RUN_FORGE` / `DRY_RUN_WECOM_SEND`。

## 文件

| 路径 | 说明 |
| --- | --- |
| `compose.yaml` | 云端 compose（仅镜像） |
| `deploy.sh` | 一键部署脚本 |
| `gateway/wecom-bridge.conf` | nginx 反代片段 |
| `.env` | **不入库**，本地填写后由脚本上传 |
| `ssl/*.pem` | **不入库**，SSH 私钥 |

## 前置

1. 腾讯云轻量已装 Docker Compose。  
2. 同机已部署 Agent Forge（或内网可达），机器账号可用。  
3. 域名已解析；nginx 可引入 `gateway/wecom-bridge.conf`。  
4. 本机可 `docker build`，并能 SSH 到云主机。

## 配置

```bash
cp ../../config/bridge.example.env docker/tencent/.env
# 编辑：
#   PUBLIC_BASE_URL=https://bridge.example.com
#   WECOM_* / AF_* / TICKET_SECRET
#   AF_BASE_URL=http://host.docker.internal:4096   # 与云上 runtime 端口一致
#   DRY_RUN_FORGE=false
#   DRY_RUN_WECOM_SEND=false
```

SSH 私钥：

```bash
mkdir -p docker/tencent/ssl
# 放入 agent-forge.pem，或 export SSH_KEY=/path/to/key.pem
```

## 部署

```bash
cd yuzq/wecom-bridge
CLOUD_HOST=<公网IP> bash docker/tencent/deploy.sh
# 可选：CLOUD_USER=ubuntu TAG=v0.1.0 SKIP_BUILD=1
```

## 企微后台

回调 URL：`https://<PUBLIC_BASE_URL 主机>/wecom/callback`  
Token / EncodingAESKey 与 `.env` 一致。

## 回滚 / 日志

```bash
ssh -i docker/tencent/ssl/agent-forge.pem ubuntu@<IP> \
  'cd /opt/yuzq-wecom-bridge && docker compose logs -f --tail=200'
```
