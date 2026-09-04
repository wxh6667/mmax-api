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

echo "===== 拉取最新代码 ====="
git pull --ff-only

echo "===== Python 语法检查 ====="
"$PYTHON_BIN" -m compileall -q mmax_api scripts/prepare_krea.py

echo "===== 重启服务 ====="
"$ROOT/scripts/restart.sh"

sleep 2

echo "===== 健康检查 ====="
"$ROOT/scripts/healthcheck.sh"

echo "更新完成。"
