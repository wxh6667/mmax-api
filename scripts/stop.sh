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

RUNTIME_DIR="${MMAX_RUNTIME_DIR:-$ROOT/runtime}"
PID_FILE="$RUNTIME_DIR/api.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "没有找到 PID 文件，服务可能未运行。"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  echo "正在停止服务，PID=$PID"
  kill "$PID"
  for _ in $(seq 1 30); do
    if ! kill -0 "$PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  if kill -0 "$PID" 2>/dev/null; then
    echo "普通停止超时，发送 SIGKILL。"
    kill -9 "$PID"
  fi
else
  echo "PID=$PID 已不存在。"
fi

rm -f "$PID_FILE"
echo "服务已停止。"
