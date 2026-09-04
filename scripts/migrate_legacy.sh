#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLD_H3="/root/autodl-tmp/h3"
MODEL_ROOT="/root/autodl-tmp/models"

cd "$ROOT"
mkdir -p "$ROOT/.deps" "$MODEL_ROOT"

if [[ -f "$OLD_H3/api.pid" ]]; then
  OLD_PID="$(cat "$OLD_H3/api.pid" || true)"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "正在停止旧 H3 API，PID=$OLD_PID"
    kill "$OLD_PID" || true
    for _ in $(seq 1 30); do
      if ! kill -0 "$OLD_PID" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    if kill -0 "$OLD_PID" 2>/dev/null; then
      echo "旧服务未正常退出，发送 SIGKILL。"
      kill -9 "$OLD_PID" || true
    fi
  fi
fi

if [[ ! -f "$ROOT/.api_key" && -f "$OLD_H3/.api_key" ]]; then
  cp "$OLD_H3/.api_key" "$ROOT/.api_key"
  chmod 600 "$ROOT/.api_key"
  echo "已迁移 API Key。"
fi

if [[ ! -d "$ROOT/.venv" && -d "$OLD_H3/venv" ]]; then
  echo "正在移动旧 Python 环境到 $ROOT/.venv"
  mv "$OLD_H3/venv" "$ROOT/.venv"
fi

if [[ ! -d "$ROOT/.deps/DiffSynth-Studio" && -d "$OLD_H3/DiffSynth-Studio" ]]; then
  echo "正在移动 DiffSynth-Studio 到 $ROOT/.deps/DiffSynth-Studio"
  mv "$OLD_H3/DiffSynth-Studio" "$ROOT/.deps/DiffSynth-Studio"
fi

if [[ ! -d "$MODEL_ROOT/h3" && -d "$OLD_H3/models" ]]; then
  echo "正在移动 H3 模型到 $MODEL_ROOT/h3"
  mv "$OLD_H3/models" "$MODEL_ROOT/h3"
fi

if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

PYTHON_BIN="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "没有找到可用的 Python 环境，请执行 bash scripts/install.sh。"
  exit 1
fi

export PYTHONPATH="$ROOT:$ROOT/.deps/DiffSynth-Studio${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON_BIN" -m pip install -e "$ROOT"

for path in \
  "$MODEL_ROOT/h3/DiffSynth-Studio/MiniMax-H3-NF4/minimax-h3-fl2va-pruned-nf4.safetensors" \
  "$MODEL_ROOT/h3/DiffSynth-Studio/MiniMax-H3-NF4/minimax-h3-text-encoder-nf4.safetensors" \
  "$MODEL_ROOT/h3/DiffSynth-Studio/MiniMax-H3-NF4/video_vae_nf4.safetensors" \
  "$MODEL_ROOT/h3/DiffSynth-Studio/MiniMax-H3-NF4/audio_vae_nf4.safetensors" \
  "$MODEL_ROOT/h3/MiniMaxAI/MiniMax-H3/FL2VA/processor"; do
  if [[ ! -e "$path" ]]; then
    echo "迁移后缺少 H3 文件：$path"
    exit 1
  fi
done

echo "===== 旧 H3 迁移完成 ====="
echo "旧 6006 已停止。"
echo "H3 模型已整理到：$MODEL_ROOT/h3"
echo "Python 环境已整理到：$ROOT/.venv"
echo "DiffSynth 已整理到：$ROOT/.deps/DiffSynth-Studio"
echo ""
echo "下一步先运行 Krea 准备脚本："
echo "$PYTHON_BIN scripts/prepare_krea.py"
