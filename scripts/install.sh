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

PYTHON_BIN="${MMAX_PYTHON_BIN:-$ROOT/.venv/bin/python}"
DIFFSYNTH_PATH="${MMAX_DIFFSYNTH_PATH:-$ROOT/.deps/DiffSynth-Studio}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "未找到独立 Python 环境，正在创建 .venv。"
  python3 -m venv "$ROOT/.venv"
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi

"$PYTHON_BIN" -m pip install -U pip setuptools wheel

if [[ ! -d "$DIFFSYNTH_PATH/.git" ]]; then
  echo "正在获取 DiffSynth-Studio。"
  mkdir -p "$(dirname "$DIFFSYNTH_PATH")"
  git clone https://github.com/modelscope/DiffSynth-Studio.git "$DIFFSYNTH_PATH"
fi

"$PYTHON_BIN" -m pip install -e "$DIFFSYNTH_PATH"
"$PYTHON_BIN" -m pip install -e "$ROOT"

mkdir -p runtime /root/autodl-tmp/outputs/videos /root/autodl-tmp/outputs/images /root/autodl-tmp/models

echo "安装完成。"
echo "Python：$PYTHON_BIN"
echo "DiffSynth：$DIFFSYNTH_PATH"
echo "如需准备 Krea 2，请执行："
echo "$PYTHON_BIN scripts/prepare_krea.py"
