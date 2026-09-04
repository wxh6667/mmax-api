#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已创建 .env，请按需要修改配置。"
fi

if [[ ! -f .api_key && -f /root/autodl-tmp/h3/.api_key ]]; then
  cp /root/autodl-tmp/h3/.api_key .api_key
  chmod 600 .api_key
  echo "已从旧 H3 服务复制 API Key。"
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON_BIN="${MMAX_PYTHON_BIN:-/root/autodl-tmp/h3/venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "找不到 Python：$PYTHON_BIN"
  exit 1
fi

"$PYTHON_BIN" -m pip install -U pip
"$PYTHON_BIN" -m pip install -e .

mkdir -p runtime /root/autodl-tmp/outputs/videos /root/autodl-tmp/outputs/images

echo "安装完成。"
echo "下一步如需准备 Krea 2，请执行："
echo "$PYTHON_BIN scripts/prepare_krea.py"
