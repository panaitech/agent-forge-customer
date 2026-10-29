#!/usr/bin/env bash
# 职责：拉起 PaddleOCR-VL 的 vLLM 容器（默认宿主机 8022）。
# 自 math-pocket/deploy/local/paddleocr-vl/run_vllm.sh 拷贝。权重挂载 /data/models/PaddleOCR-VL-1.5。
# RTX 3060 12GB 上 vLLM 并发与显存/视觉 token 强相关：并发主要由 --max-num-seqs 与 --max-num-batched-tokens 控制。
# - 提高并发：增大 VLLM_MAX_NUM_SEQS（与「同时处理请求数」最相关，旧脚本写死为 1 时等于完全串行）。
# - 若 OOM/驱动重置：先降低 VLLM_MAX_NUM_SEQS，或把 VLLM_GPU_MEMORY_UTILIZATION 从 0.9 降到 0.80～0.85，或让前端/上游限制图片长边与体积（单张题图默认长边 1920、500KB，见 web-admin: utils/ocrImageUpload.ts）。
# - 大分辨率 → 每请求视觉 token 更多、KV/激活显存更紧；在固定显存下应适当降低长边以换取更高 VLLM_MAX_NUM_SEQS。
# 在启动前可 `export` 以下变量再执行本脚本；未设置时使用默认值（偏保守、多数 12G 可跑稳）。
: "${VLLM_GPU_MEMORY_UTILIZATION:=0.8}"
: "${VLLM_MAX_MODEL_LEN:=4096}"
# 与吞吐/批处理相关，可与 seq 数同向略增；若 OOM 可降到 2048
: "${VLLM_MAX_NUM_BATCHED_TOKENS:=4096}"
# 同时可排队执行的序列数（=实际侧并发上界之一）；2～4 在 12GB 上较常见，从 2 起压测
: "${VLLM_MAX_NUM_SEQS:=4}"

set -euo pipefail

CONTAINER_NAME="vllm-paddleocr"

# 如果容器已在运行且健康，跳过
if docker ps --filter "name=${CONTAINER_NAME}" --filter "status=running" --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "[vllm] 容器 ${CONTAINER_NAME} 已在运行，跳过启动"
  exit 0
fi

# 容器存在但已停止，清理后重建
if docker ps -a --filter "name=${CONTAINER_NAME}" --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "[vllm] 容器 ${CONTAINER_NAME} 已存在但未运行，清理后重建"
  docker stop "${CONTAINER_NAME}" 2>/dev/null || true
  docker rm "${CONTAINER_NAME}" 2>/dev/null || true
fi

docker run -d \
  --name vllm-paddleocr \
  --gpus all \
  -p 8022:8000 \
  -v /data/models/PaddleOCR-VL-1.5:/model \
  --shm-size=16g \
  ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-genai-vllm-server:latest-nvidia-gpu \
  sh -c "cd /model && python3 -m vllm.entrypoints.openai.api_server \
    --model /model \
    --trust-remote-code \
    --host 0.0.0.0 \
    --port 8000 \
    --gpu-memory-utilization ${VLLM_GPU_MEMORY_UTILIZATION} \
    --max-model-len ${VLLM_MAX_MODEL_LEN} \
    --max-num-batched-tokens ${VLLM_MAX_NUM_BATCHED_TOKENS} \
    --max-num-seqs ${VLLM_MAX_NUM_SEQS}"
