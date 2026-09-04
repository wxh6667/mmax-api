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
LOG_FILE="$RUNTIME_DIR/api.log"

if [[ ! -f "$LOG_FILE" ]]; then
  echo "日志文件不存在：$LOG_FILE"
  exit 1
fi

MODE="follow"
LINES=200

if [[ ${1:-} == "--once" ]]; then
  MODE="once"
  LINES="${2:-200}"
elif [[ ${1:-} == "--errors" ]]; then
  echo "===== 最近错误日志 ====="
  tail -n "${2:-500}" "$LOG_FILE" | grep -Ei 'traceback|error|exception|failed|keyerror|runtimeerror' || true
  exit 0
elif [[ -n ${1:-} ]]; then
  LINES="$1"
fi

echo "===== 日志文件：$LOG_FILE ====="

if [[ "$MODE" == "once" ]]; then
  tail -n "$LINES" "$LOG_FILE"
else
  echo "持续追踪最近 $LINES 行，按 Ctrl+C 退出。"
  tail -n "$LINES" -f "$LOG_FILE"
fi
