#!/usr/bin/env bash
# Start the local vLLM server the agent talks to. Run from your own terminal (it stays in the foreground; Ctrl-C stops it).
#   GPU=1 scripts/serve_llm.sh          # pick the card (default 0)
#   MODEL_DIR=... MODEL_NAME=... scripts/serve_llm.sh
set -euo pipefail
ENV_BIN=/home/sheshnagnobackup/mnguyen/envs/registrar/bin
MODEL_DIR=${MODEL_DIR:-/home/sheshnagnobackup/mnguyen/models/Qwen3.5-27B}
MODEL_NAME=${MODEL_NAME:-qwen3.5-27b}
PORT=${PORT:-8000}
export CUDA_VISIBLE_DEVICES=${GPU:-0}

exec "$ENV_BIN/vllm" serve "$MODEL_DIR" \
  --served-model-name "$MODEL_NAME" \
  --port "$PORT" \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 64 \
  --limit-mm-per-prompt '{"image": 0, "video": 0}' \
  --structured-outputs-config.backend xgrammar
