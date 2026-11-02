#!/usr/bin/env bash
# 职责：WeCom Bridge 一键部署到腾讯云 —— 本机构建镜像 → 上传 → docker load → compose up。
#
# 用法（在 wecom-bridge 目录）：
#   CLOUD_HOST=<公网IP> bash docker/tencent/deploy.sh
# 可选：CLOUD_USER · SSH_KEY · TAG · SKIP_BUILD=1 · CLOUD_DIR · ENV_FILE
#
# 云端目录默认 /opt/yuzq-wecom-bridge，仅存放 compose、.env、exceptions、镜像 tar（无源码树）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${BRIDGE_ROOT}"

CLOUD_USER="${CLOUD_USER:-ubuntu}"
CLOUD_HOST="${CLOUD_HOST:-}"
CLOUD_DIR="${CLOUD_DIR:-/opt/yuzq-wecom-bridge}"
TAG="${TAG:-latest}"
IMAGE="yuzq-wecom-bridge"
ARTIFACT_DIR="${BRIDGE_ROOT}/.deploy"
IMAGE_TAR="${ARTIFACT_DIR}/${IMAGE}-${TAG}.tar.gz"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"
EXCEPTIONS_FILE="${EXCEPTIONS_FILE:-${BRIDGE_ROOT}/../config/exceptions.example.json}"

# SSH 私钥：优先 docker/tencent/ssl/，其次环境变量
if [[ -n "${SSH_KEY:-}" ]]; then
  :
elif [[ -f "${SCRIPT_DIR}/ssl/agent-forge.pem" ]]; then
  SSH_KEY="${SCRIPT_DIR}/ssl/agent-forge.pem"
elif [[ -f "${BRIDGE_ROOT}/../../../agent-forge-runtime/docker/tencent/ssl/agent-forge.pem" ]]; then
  SSH_KEY="${BRIDGE_ROOT}/../../../agent-forge-runtime/docker/tencent/ssl/agent-forge.pem"
else
  SSH_KEY="${SCRIPT_DIR}/ssl/agent-forge.pem"
fi

if [[ -z "${CLOUD_HOST}" ]]; then
  echo "请设置 CLOUD_HOST（腾讯云轻量公网 IP）" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "缺少云端 env 文件: ${ENV_FILE}" >&2
  echo "请复制样例并填写生产值：" >&2
  echo "  cp ${BRIDGE_ROOT}/../config/bridge.example.env ${ENV_FILE}" >&2
  echo "生产务必设置 PUBLIC_BASE_URL=https://你的域名 ，并关闭 DRY_RUN_*" >&2
  exit 1
fi

if [[ ! -f "${SSH_KEY}" ]]; then
  echo "缺少 SSH 私钥: ${SSH_KEY}" >&2
  echo "请放到 ${SCRIPT_DIR}/ssl/agent-forge.pem 或 export SSH_KEY=/path/to/key.pem" >&2
  exit 1
fi
chmod 600 "${SSH_KEY}" 2>/dev/null || true

SSH_OPTS=(-i "${SSH_KEY}" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 -o ServerAliveInterval=15)
REMOTE="${CLOUD_USER}@${CLOUD_HOST}"

retry() {
  local n=0 max=3 wait=5
  until "$@"; do
    n=$((n + 1))
    if [[ ${n} -ge ${max} ]]; then
      echo "命令失败（已重试 ${max} 次）: $*" >&2
      return 1
    fi
    echo "连接失败，${wait}s 后重试 (${n}/${max})..."
    sleep "${wait}"
  done
}

# 上传前校验生产关键项
if grep -qE '^DRY_RUN_FORGE=true' "${ENV_FILE}" 2>/dev/null; then
  echo "警告: ${ENV_FILE} 中 DRY_RUN_FORGE=true（生产通常应为 false）" >&2
fi
if ! grep -qE '^PUBLIC_BASE_URL=https://' "${ENV_FILE}" 2>/dev/null; then
  echo "警告: PUBLIC_BASE_URL 建议为 https:// 公网域名（企微确认链接依赖）" >&2
fi

echo "=== WeCom Bridge 部署（腾讯云）==="
echo "  目标: ${REMOTE}"
echo "  目录: ${CLOUD_DIR}"
echo "  镜像: ${IMAGE}:${TAG}"
echo ""

# 1-2. 本机构建并导出
if [[ "${SKIP_BUILD:-}" == "1" && -f "${IMAGE_TAR}" ]]; then
  echo "[1-2/5] 跳过构建（SKIP_BUILD=1，使用 ${IMAGE_TAR}）"
else
  echo "[1/5] 本机构建镜像..."
  docker build -f docker/Dockerfile -t "${IMAGE}:${TAG}" .
  echo "[2/5] 导出镜像包..."
  mkdir -p "${ARTIFACT_DIR}"
  docker save "${IMAGE}:${TAG}" | gzip > "${IMAGE_TAR}"
fi

# 3. 云目录
echo "[3/5] 准备云服务器目录..."
retry ssh "${SSH_OPTS[@]}" "${REMOTE}" "set -euo pipefail
  if ! mkdir -p ${CLOUD_DIR}/gateway ${CLOUD_DIR}/ssl 2>/dev/null; then
    sudo -n mkdir -p ${CLOUD_DIR}/gateway ${CLOUD_DIR}/ssl
    sudo -n chown -R \$(whoami):\$(whoami) ${CLOUD_DIR}
  fi
  chown -R \$(whoami):\$(whoami) ${CLOUD_DIR} 2>/dev/null || true
"

# 4. 上传
echo "[4/5] 上传镜像、compose、env、例外表、网关片段..."
retry scp "${SSH_OPTS[@]}" "${IMAGE_TAR}" "${REMOTE}:${CLOUD_DIR}/"
retry scp "${SSH_OPTS[@]}" "${SCRIPT_DIR}/compose.yaml" "${REMOTE}:${CLOUD_DIR}/docker-compose.yml"
retry scp "${SSH_OPTS[@]}" "${ENV_FILE}" "${REMOTE}:${CLOUD_DIR}/.env"
retry scp "${SSH_OPTS[@]}" "${EXCEPTIONS_FILE}" "${REMOTE}:${CLOUD_DIR}/exceptions.json"
retry scp "${SSH_OPTS[@]}" "${SCRIPT_DIR}/gateway/wecom-bridge.conf" "${REMOTE}:${CLOUD_DIR}/gateway/wecom-bridge.conf"

# 5. load + up
echo "[5/5] 云上加载镜像并启动..."
retry ssh "${SSH_OPTS[@]}" "${REMOTE}" "set -euo pipefail
  cd ${CLOUD_DIR}
  docker load < ${IMAGE}-${TAG}.tar.gz
  export TAG=${TAG}
  docker compose --env-file .env -f docker-compose.yml up -d --remove-orphans
  sleep 2
  curl -sf http://127.0.0.1:8787/healthz || (docker compose -f docker-compose.yml logs --tail=80 && exit 1)
  echo OK
"

echo ""
echo "部署完成。"
echo "  本机探测: ssh ${REMOTE} 'curl -s http://127.0.0.1:8787/healthz'"
echo "  请将 nginx 接入 ${CLOUD_DIR}/gateway/wecom-bridge.conf"
echo "  企微回调: \${PUBLIC_BASE_URL}/wecom/callback"
