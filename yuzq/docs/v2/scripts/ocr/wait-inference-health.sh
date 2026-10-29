#!/usr/bin/env bash
# 职责：等待 vLLM 与 OCR 的 /health 返回 200，供启动脚本 source。
# 自 math-pocket/deploy/shared/wait-inference-health.sh 拷贝。

wait_vllm_health() {
  local url="${VLLM_HEALTH_URL:-http://127.0.0.1:8022/health}"
  local attempts="${VLLM_WAIT_ATTEMPTS:-60}"
  local interval="${VLLM_WAIT_INTERVAL_SEC:-5}"

  echo "  等待 vLLM health 200 (${url})..."
  for i in $(seq 1 "${attempts}"); do
    if curl -sf --max-time 5 --noproxy '*' "${url}" > /dev/null 2>&1; then
      echo "  vLLM 已就绪 (${i}/${attempts})"
      return 0
    fi
    echo "  等待 vLLM... (${i}/${attempts})"
    sleep "${interval}"
  done

  echo "  vLLM 在 $((attempts * interval))s 内未就绪" >&2
  return 1
}

_get_port_listener_pid() {
  local port="$1"
  local pid=""
  if command -v ss &>/dev/null; then
    pid=$(ss -tlnp "sport = :${port}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1 || true)
  elif command -v lsof &>/dev/null; then
    pid=$(lsof -t -i :"${port}" -sTCP:LISTEN 2>/dev/null | head -1 || true)
  fi
  echo "${pid}"
}

stop_ocr_listener_if_any() {
  local port="${OCR_PORT:-18088}"
  local pid="$(_get_port_listener_pid "${port}")"
  if [[ -z "${pid}" ]]; then
    return 0
  fi

  echo "  停止旧 OCR 进程 (pid=${pid})..."
  kill "${pid}" 2>/dev/null || true
  for _ in $(seq 1 10); do
    if [[ -z "$(_get_port_listener_pid "${port}")" ]]; then
      echo "  端口 ${port} 已释放"
      return 0
    fi
    sleep 1
  done

  kill -9 "${pid}" 2>/dev/null || true
  sleep 1
}

wait_ocr_health() {
  local url="${OCR_HEALTH_URL:-http://127.0.0.1:18088/health}"
  local attempts="${OCR_WAIT_ATTEMPTS:-60}"
  local interval="${OCR_WAIT_INTERVAL_SEC:-2}"
  local port="${OCR_PORT:-18088}"

  echo "  等待 OCR health 200 (${url})..."
  for i in $(seq 1 "${attempts}"); do
    if curl -sf --max-time 5 --noproxy '*' "${url}" > /dev/null 2>&1; then
      echo "  OCR 已就绪 (${i}/${attempts})"
      return 0
    fi
    if [[ -n "${OCR_PID:-}" ]] && ! kill -0 "${OCR_PID}" 2>/dev/null; then
      if command -v ss &>/dev/null; then
        if ! ss -tlnp "sport = :${port}" 2>/dev/null | grep -q LISTEN; then
          echo "  OCR 进程已退出且 ${port} 未监听 (pid=${OCR_PID})" >&2
          return 1
        fi
      fi
    fi
    echo "  等待 OCR... (${i}/${attempts})"
    sleep "${interval}"
  done

  echo "  OCR 在 $((attempts * interval))s 内未就绪" >&2
  return 1
}

# 云服务器 API 经蜻蜓访问本机 OCR 时使用（OCR_HEALTH_URL / OCR_SERVICE_URL 为公网 HTTPS）
wait_remote_ocr_health() {
  local url="${OCR_HEALTH_URL:-}"
  if [[ -z "${url}" ]]; then
    local base="${OCR_SERVICE_URL:-}"
    base="${base%/}"
    [[ -n "${base}" ]] || return 0
    url="${base}/health"
  fi
  if [[ "${url}" == *"host.docker.internal"* || "${url}" == *"127.0.0.1"* ]]; then
    return 0
  fi

  local attempts="${OCR_WAIT_ATTEMPTS:-30}"
  local interval="${OCR_WAIT_INTERVAL_SEC:-3}"
  echo "  等待远程 OCR health 200 (${url})..."
  for i in $(seq 1 "${attempts}"); do
    if curl -sf --max-time 10 "${url}" > /dev/null 2>&1; then
      echo "  远程 OCR 已就绪 (${i}/${attempts})"
      return 0
    fi
    echo "  等待远程 OCR... (${i}/${attempts})"
    sleep "${interval}"
  done
  echo "  远程 OCR 在 $((attempts * interval))s 内未就绪（可稍后在本机启动 OCR）" >&2
  return 1
}
