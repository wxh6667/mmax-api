#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON_BIN="${MMAX_PYTHON_BIN:-/root/autodl-tmp/h3/venv/bin/python}"
DIFFSYNTH_PATH="${MMAX_DIFFSYNTH_PATH:-/root/autodl-tmp/h3/DiffSynth-Studio}"
HOST="${MMAX_HOST:-0.0.0.0}"
PORT="${MMAX_PORT:-6006}"
RUNTIME_DIR="${MMAX_RUNTIME_DIR:-$ROOT/runtime}"

mkdir -p "$RUNTIME_DIR"
PID_FILE="$RUNTIME_DIR/api.pid"
LOG_FILE="$RUNTIME_DIR/api.log"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "服务已经在运行，PID=$(cat "$PID_FILE")"
  exit 0
fi

export DIFFSYNTH_SKIP_DOWNLOAD=True
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export PYTHONPATH="$ROOT:$DIFFSYNTH_PATH${PYTHONPATH:+:$PYTHONPATH}"

nohup "$PYTHON_BIN" -m uvicorn mmax_api.api:app \
  --host "$HOST" \
  --port "$PORT" \
  --workers 1 \
  >"$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"
echo "服务已启动，PID=$(cat "$PID_FILE")，日志：$LOG_FILE"
