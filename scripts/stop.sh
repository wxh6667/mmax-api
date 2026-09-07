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

is_mmax_pid() {
  local pid="$1"
  local cmdline
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  [[ -r "/proc/$pid/cmdline" ]] || return 1
  cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
  [[ "$cmdline" == *"-m mmax_api.run"* || "$cmdline" == *"uvicorn mmax_api.api:app"* ]]
}

if [[ ! -f "$PID_FILE" ]]; then
  echo "没有找到 PID 文件，服务可能未运行。"
  exit 0
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if ! is_mmax_pid "$PID"; then
  echo "PID 文件已陈旧或不属于 mmax-api（PID=${PID:-未知}），仅清理 PID 文件，不停止其他进程。"
  rm -f "$PID_FILE"
  exit 0
fi

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

rm -f "$PID_FILE"
echo "服务已停止。"
