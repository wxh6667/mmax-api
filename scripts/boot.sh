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
BOOT_LOG="$RUNTIME_DIR/boot.log"
DELAY="${MMAX_BOOT_DELAY:-20}"
PORT="${MMAX_PORT:-6006}"

mkdir -p "$RUNTIME_DIR"
exec >>"$BOOT_LOG" 2>&1

echo
echo "===== $(date '+%F %T') mmax-api 开机启动 ====="
echo "延迟 ${DELAY}s，等待 AutoDL 完成 GPU、网络和目录初始化。"
sleep "$DELAY"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "启动失败：缺少 $ROOT/.venv/bin/python"
  exit 1
fi

if [[ ! -f "$ROOT/scripts/start.sh" ]]; then
  echo "启动失败：缺少 $ROOT/scripts/start.sh"
  exit 1
fi

bash "$ROOT/scripts/start.sh"

echo "等待 /health 就绪。"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "mmax-api 已就绪：http://127.0.0.1:${PORT}/health"
    exit 0
  fi
  sleep 2
done

echo "启动后健康检查超时，请查看：$ROOT/runtime/api.log"
exit 1
