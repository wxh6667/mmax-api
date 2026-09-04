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

PYTHON_BIN="${MMAX_PYTHON_BIN:-$ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "找不到 Python：$PYTHON_BIN，请先执行 bash scripts/install.sh。"
  exit 1
fi

echo "===== 拉取最新代码 ====="
git pull --ff-only

echo "===== Python 语法检查 ====="
"$PYTHON_BIN" -m compileall -q mmax_api scripts/prepare_krea.py

echo "===== 重启服务 ====="
bash "$ROOT/scripts/restart.sh"

sleep 2

echo "===== 健康检查 ====="
bash "$ROOT/scripts/healthcheck.sh"

echo "更新完成。"
