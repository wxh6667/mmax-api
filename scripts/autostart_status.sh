#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JUPYTER_PYTHON="${MMAX_JUPYTER_PYTHON:-/root/miniconda3/bin/python}"
JUPYTER_BIN="${MMAX_JUPYTER_BIN:-/root/miniconda3/bin/jupyter}"
CONFIG_FILE="/root/.jupyter/jupyter_server_config.d/mmax_api_autostart.json"

echo "===== AutoDL Jupyter 进程 ====="
ps -ef | grep -E '[j]upyter-(lab|server)' || true

echo
echo "===== 自启动配置 ====="
if [[ -f "$CONFIG_FILE" ]]; then
  echo "已安装：$CONFIG_FILE"
  cat "$CONFIG_FILE"
else
  echo "未安装：$CONFIG_FILE"
fi

echo
echo "===== Jupyter 扩展导入 ====="
if [[ -x "$JUPYTER_PYTHON" ]]; then
  "$JUPYTER_PYTHON" - <<'PY' || true
try:
    import mmax_api.jupyter_boot
except Exception as exc:
    print(f"导入失败：{exc}")
else:
    print("导入成功：mmax_api.jupyter_boot")
PY
else
  echo "找不到：$JUPYTER_PYTHON"
fi

echo
echo "===== Jupyter Server 扩展列表 ====="
if [[ -x "$JUPYTER_BIN" ]]; then
  "$JUPYTER_BIN" server extension list 2>&1 || true
else
  echo "找不到：$JUPYTER_BIN"
fi

echo
echo "===== mmax-api 当前状态 ====="
if curl -fsS http://127.0.0.1:6006/health; then
  echo
else
  echo "6006 当前未就绪。"
fi

echo
echo "===== 最近开机启动日志 ====="
for log in "$ROOT/runtime/boot.log" "$ROOT/runtime/jupyter-autostart.log"; do
  echo "--- $log ---"
  if [[ -f "$log" ]]; then
    tail -50 "$log"
  else
    echo "尚无日志。"
  fi
done
