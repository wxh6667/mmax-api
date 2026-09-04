#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JUPYTER_PYTHON="${MMAX_JUPYTER_PYTHON:-/root/miniconda3/bin/python}"
CONFIG_FILE="/root/.jupyter/jupyter_server_config.d/mmax_api_autostart.json"

if [[ -x "$JUPYTER_PYTHON" ]]; then
  SITE_PACKAGES="$($JUPYTER_PYTHON - <<'PY'
import site
paths = site.getsitepackages()
print(paths[0] if paths else "")
PY
)"
else
  SITE_PACKAGES=""
fi

PTH_FILE="${SITE_PACKAGES:+$SITE_PACKAGES/mmax_api_autostart.pth}"

if [[ -f "$CONFIG_FILE" ]]; then
  rm -f "$CONFIG_FILE"
  echo "已删除 Jupyter 自启动配置：$CONFIG_FILE"
else
  echo "Jupyter 自启动配置不存在：$CONFIG_FILE"
fi

if [[ -n "$PTH_FILE" && -f "$PTH_FILE" ]]; then
  rm -f "$PTH_FILE"
  echo "已删除 Python 路径文件：$PTH_FILE"
fi

echo "mmax-api 开机自启动已卸载。当前正在运行的 6006 服务不会被停止。"
