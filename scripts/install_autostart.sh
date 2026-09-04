#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JUPYTER_PYTHON="${MMAX_JUPYTER_PYTHON:-/root/miniconda3/bin/python}"
JUPYTER_BIN="${MMAX_JUPYTER_BIN:-/root/miniconda3/bin/jupyter}"
CONFIG_DIR="/root/.jupyter/jupyter_server_config.d"
CONFIG_FILE="$CONFIG_DIR/mmax_api_autostart.json"

if [[ ! -x "$JUPYTER_PYTHON" ]]; then
  echo "安装失败：找不到 AutoDL Jupyter Python：$JUPYTER_PYTHON"
  exit 1
fi
if [[ ! -x "$JUPYTER_BIN" ]]; then
  echo "安装失败：找不到 AutoDL Jupyter：$JUPYTER_BIN"
  exit 1
fi
if [[ ! -f "$ROOT/mmax_api/jupyter_boot.py" ]]; then
  echo "安装失败：缺少 $ROOT/mmax_api/jupyter_boot.py"
  exit 1
fi
if [[ ! -f "$ROOT/scripts/boot.sh" ]]; then
  echo "安装失败：缺少 $ROOT/scripts/boot.sh"
  exit 1
fi

SITE_PACKAGES="$($JUPYTER_PYTHON - <<'PY'
import site
paths = site.getsitepackages()
if not paths:
    raise SystemExit("无法找到 site-packages")
print(paths[0])
PY
)"
PTH_FILE="$SITE_PACKAGES/mmax_api_autostart.pth"

mkdir -p "$CONFIG_DIR"
printf '%s\n' "$ROOT" > "$PTH_FILE"
cat > "$CONFIG_FILE" <<'JSON'
{
  "ServerApp": {
    "jpserver_extensions": {
      "mmax_api.jupyter_boot": true
    }
  }
}
JSON

# 验证 AutoDL 自带的 Jupyter Python 能导入扩展。
"$JUPYTER_PYTHON" - <<'PY'
import mmax_api.jupyter_boot
print("Jupyter 扩展导入成功：mmax_api.jupyter_boot")
PY

echo
echo "===== Jupyter Server 扩展配置 ====="
"$JUPYTER_BIN" server extension list 2>&1 || true

echo
echo "===== mmax-api 开机自启动已安装 ====="
echo "Python 路径文件：$PTH_FILE"
echo "Jupyter 配置：$CONFIG_FILE"
echo "启动脚本：$ROOT/scripts/boot.sh"
echo
echo "注意：当前已经运行的 JupyterLab 不会热加载新扩展。"
echo "下次 AutoDL 实例关机再开机时，平台启动 JupyterLab 后会自动拉起 mmax-api。"
