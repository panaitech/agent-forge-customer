#!/usr/bin/env bash
# 职责：启动本机 PaddleOCR HTTP 服务（默认 127.0.0.1:18088）。
# 不用 8088：该端口已被本机 Airflow 占用。
# 自 math-pocket/services/ocr-inference/scripts/start_ocr_inference.sh 拷贝。
# 推理代码仍在 math-pocket，不跟本目录走。换机器时设 MATH_POCKET_ROOT 或 OCR_SERVICE_DIR。
set -euo pipefail

MATH_POCKET_ROOT="${MATH_POCKET_ROOT:-/home/pan/work/math/github/math-pocket}"
SERVICE_DIR="${OCR_SERVICE_DIR:-${MATH_POCKET_ROOT}/services/ocr-inference}"
if [[ ! -d "${SERVICE_DIR}" ]]; then
  echo "[ocr-inference] 找不到服务目录 ${SERVICE_DIR}" >&2
  echo "[ocr-inference] 请设置 MATH_POCKET_ROOT 或 OCR_SERVICE_DIR" >&2
  exit 1
fi
HOST="${OCR_HOST:-0.0.0.0}"
PORT="${OCR_PORT:-18088}"
CONDA_ENV_NAME="${OCR_CONDA_ENV_NAME:-paddleocr}"

cd "${SERVICE_DIR}"

# 如果端口已被监听，说明进程已在运行，跳过
if command -v ss &>/dev/null; then
  LISTENING=$(ss -tlnp "sport = :${PORT}" 2>/dev/null | tail -n +2 | head -1)
elif command -v lsof &>/dev/null; then
  LISTENING=$(lsof -i :"${PORT}" -sTCP:LISTEN 2>/dev/null | tail -n +2 | head -1)
else
  LISTENING=""
fi
if [[ -n "${LISTENING}" ]]; then
  echo "[ocr-inference] 端口 ${PORT} 已被占用，ocr-inference 已在运行，跳过启动"
  exit 0
fi

# PaddleOCR-VL：VL 识别走独立 vLLM（需先起 deploy/paddleocr-vl/run_vllm.sh 等）。启动前可 override。
export OCR_VL_REC_BACKEND="${OCR_VL_REC_BACKEND:-vllm-server}"
export OCR_VL_REC_SERVER_URL="${OCR_VL_REC_SERVER_URL:-http://127.0.0.1:8022/v1}"
# 与 vLLM --max-num-seqs / 显存自洽时调整；已在外部 export 时保留外置值
export OCR_VL_REC_MAX_CONCURRENCY="${OCR_VL_REC_MAX_CONCURRENCY:-4}"
# 与 vLLM 的 --model 注册名一致（run_vllm.sh 为 /model）；若你用 --served-model-name 改名则同步改此变量
export OCR_VL_REC_API_MODEL_NAME="${OCR_VL_REC_API_MODEL_NAME:-/model}"
# Paddle 默认 max_new_tokens=4096 会与 max_model_len=4096 冲突；压到 2048（可按页调大/调小）
export OCR_VL_MAX_NEW_TOKENS="${OCR_VL_MAX_NEW_TOKENS:-2048}"
# 禁用 vLLM 回退到 native 推理
export OCR_VLLM_FALLBACK_TO_NATIVE=0

# OCR / vLLM 均为本机服务，不走 shell 全局代理
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost
export OCR_VL_REC_HEALTH_TIMEOUT_SEC="${OCR_VL_REC_HEALTH_TIMEOUT_SEC:-10}"

# shellcheck disable=SC1091
source "${HOME}/soft/miniconda3/etc/profile.d/conda.sh"
# 环境名来自 math-pocket。本机若从未建过，conda 只会报 EnvironmentNameNotFound。
if ! conda env list | awk '{print $1}' | grep -qx "${CONDA_ENV_NAME}"; then
  echo "[ocr-inference] 找不到 conda 环境 ${CONDA_ENV_NAME}" >&2
  echo "[ocr-inference] 创建示例：conda create -n ${CONDA_ENV_NAME} python=3.10 -y && conda activate ${CONDA_ENV_NAME} && pip install -r ${SERVICE_DIR}/requirements.txt" >&2
  echo "[ocr-inference] 或指定已有环境：OCR_CONDA_ENV_NAME=<名称> bash ocr/start_ocr_inference.sh" >&2
  echo "[ocr-inference] quant-agent 里的 paddleocr 2.10 没有 PaddleOCRVL，不能用来启动本服务。" >&2
  exit 1
fi
conda activate "${CONDA_ENV_NAME}"

echo "[ocr-inference] conda_env=${CONDA_ENV_NAME}"

echo "[ocr-inference] host=${HOST} port=${PORT}"
echo "[ocr-inference] model_dir=${PADDLEOCR_VL_MODEL_DIR:-/data/models/PaddleOCR-VL-1.5}"
echo "[ocr-inference] vl_rec_backend=${OCR_VL_REC_BACKEND} server_url=${OCR_VL_REC_SERVER_URL} max_concurrency=${OCR_VL_REC_MAX_CONCURRENCY} api_model_name=${OCR_VL_REC_API_MODEL_NAME} max_new_tokens=${OCR_VL_MAX_NEW_TOKENS}"
if [[ -n "${OCR_MARKDOWN_SAVE_DIR:-}" ]]; then
  echo "[ocr-inference] markdown_save_dir=${OCR_MARKDOWN_SAVE_DIR}"
fi

exec uvicorn app.main:app --host "${HOST}" --port "${PORT}"
