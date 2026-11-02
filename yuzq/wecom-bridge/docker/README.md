# WeCom Bridge · Docker 部署

本地开发与腾讯云生产共用同一 `Dockerfile`，用不同 compose / 脚本区分环境。

| 环境 | 入口 | 说明 |
| --- | --- | --- |
| 本机 dev | `bash docker/local/deploy.sh` | 构建并起容器；默认 dry-run；经 `host.docker.internal` 访问宿主 AF |
| 腾讯云 | `CLOUD_HOST=... bash docker/tencent/deploy.sh` | 本机构建 → 上传 → load；端口仅绑 127.0.0.1；nginx TLS 反代 |

## 快速开始（本机）

```bash
cd yuzq/wecom-bridge
cp ../config/bridge.example.env .env
# 按需修改 WECOM_* / AF_* ；本地默认可保持 DRY_RUN_*=true
bash docker/local/deploy.sh up
curl -s http://127.0.0.1:8787/healthz
```

## 腾讯云

见 [`tencent/README.md`](tencent/README.md)。

## 镜像

```bash
# 在 wecom-bridge 目录
docker build -f docker/Dockerfile -t yuzq-wecom-bridge:latest .
```

数据卷持久化身份库与附件：`bridge-data` → `/app/data`。
