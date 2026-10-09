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

# 仓库托管在 GitHub，AutoDL 环境用学术资源加速拉取；
# 加速仅覆盖 GitHub/HuggingFace，pull 完立即关闭，避免影响其它网络访问。
accel_on() {
  if [[ -f /etc/network_turbo ]]; then
    # shellcheck disable=SC1091
    source /etc/network_turbo
    echo "已启用 AutoDL 学术资源加速（GitHub）。"
    return 0
  fi
  return 1
}

accel_off() {
  unset http_proxy https_proxy
}

echo "===== 拉取最新代码 ====="
accel_on || true
git pull --ff-only
accel_off

echo "===== Python 语法检查 ====="
"$PYTHON_BIN" -m compileall -q mmax_api

echo "===== 重启服务 ====="
bash "$ROOT/scripts/restart.sh"

sleep 2

echo "===== 健康检查 ====="
bash "$ROOT/scripts/healthcheck.sh"

echo "更新完成。"
