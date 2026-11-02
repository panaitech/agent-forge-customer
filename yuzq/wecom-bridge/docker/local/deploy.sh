#!/usr/bin/env bash
# 职责：本机 Docker 部署 WeCom Bridge（构建 + compose up；支持与本地 bun AF 联调）。
#
# 用法（在 wecom-bridge 目录或任意目录）：
#   bash docker/local/deploy.sh          # 构建并启动
#   bash docker/local/deploy.sh up
#   bash docker/local/deploy.sh down
#   bash docker/local/deploy.sh logs
#   bash docker/local/deploy.sh status
# 可选：ENV_FILE · SKIP_BUILD=1 · TAG · BRIDGE_HOST_PORT
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${BRIDGE_ROOT}"

CMD="${1:-up}"
ENV_FILE="${ENV_FILE:-${BRIDGE_ROOT}/.env}"
EXAMPLE_ENV="${BRIDGE_ROOT}/../config/bridge.example.env"
GENERATED="${SCRIPT_DIR}/.env.generated"
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
TAG="${TAG:-latest}"
BRIDGE_HOST_PORT="${BRIDGE_HOST_PORT:-8787}"

if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${EXAMPLE_ENV}" ]]; then
    echo "缺少 ${ENV_FILE}，可从样例复制：" >&2
    echo "  cp ${EXAMPLE_ENV} ${ENV_FILE}" >&2
  else
    echo "缺少环境文件: ${ENV_FILE}" >&2
  fi
  exit 1
fi

# 生成本地 compose 用 env：环回地址改为 host.docker.internal，便于容器访问宿主 AF
gen_env() {
  local tmp
  tmp="$(mktemp)"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    case "${line}" in
      ""|\#*) continue ;;
    esac
    # 仅改写 AF / PUBLIC 相关常见环回；企微 API 保持公网
    if [[ "${line}" == AF_BASE_URL=* ]] || [[ "${line}" == AF_CONSOLE_BASE_URL=* ]]; then
      line="${line//localhost/host.docker.internal}"
      line="${line//127.0.0.1/host.docker.internal}"
    fi
    printf '%s\n' "${line}" >> "${tmp}"
  done < "${ENV_FILE}"

  {
    echo "TAG=${TAG}"
    echo "BRIDGE_HOST_PORT=${BRIDGE_HOST_PORT}"
    # 未显式设置时，本地默认 dry-run，避免误打生产企微/AF
    if ! grep -q '^DRY_RUN_FORGE=' "${tmp}" 2>/dev/null; then
      echo "DRY_RUN_FORGE=true"
    fi
    if ! grep -q '^DRY_RUN_WECOM_SEND=' "${tmp}" 2>/dev/null; then
      echo "DRY_RUN_WECOM_SEND=true"
    fi
  } >> "${tmp}"

  mv "${tmp}" "${GENERATED}"
  chmod 600 "${GENERATED}"
}

compose() {
  docker compose -f "${COMPOSE_FILE}" --env-file "${GENERATED}" "$@"
}

case "${CMD}" in
  up|start|"")
    echo "=== WeCom Bridge 本机 Docker 部署 ==="
    echo "  env:  ${ENV_FILE}"
    echo "  url:  http://127.0.0.1:${BRIDGE_HOST_PORT}/healthz"
    echo "  回调: http://127.0.0.1:${BRIDGE_HOST_PORT}/wecom/callback （需公网穿透才可配企微）"
    echo ""
    gen_env
    if [[ "${SKIP_BUILD:-}" == "1" ]]; then
      echo "[1/2] 跳过构建（SKIP_BUILD=1）"
      compose up -d --remove-orphans
    else
      echo "[1/2] 构建并启动..."
      compose up -d --build --remove-orphans
    fi
    echo "[2/2] 等待健康检查..."
    ok=0
    for _ in $(seq 1 30); do
      if curl -sf "http://127.0.0.1:${BRIDGE_HOST_PORT}/healthz" >/dev/null 2>&1; then
        ok=1
        break
      fi
      sleep 2
    done
    if [[ "${ok}" -eq 1 ]]; then
      echo "就绪: http://127.0.0.1:${BRIDGE_HOST_PORT}/healthz"
    else
      echo "健康检查超时，请查看: bash docker/local/deploy.sh logs" >&2
      exit 1
    fi
    ;;
  down|stop)
    gen_env
    compose down --remove-orphans
    ;;
  logs)
    gen_env
    compose logs -f --tail=200
    ;;
  status|ps)
    gen_env
    compose ps
    curl -sf "http://127.0.0.1:${BRIDGE_HOST_PORT}/healthz" && echo || echo "healthz unreachable"
    ;;
  *)
    echo "用法: $0 {up|down|logs|status}" >&2
    exit 1
    ;;
esac
