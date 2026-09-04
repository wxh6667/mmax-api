#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLD_H3="/root/autodl-tmp/h3"
MODEL_ROOT="/root/autodl-tmp/models"

cd "$ROOT"
mkdir -p "$ROOT/.deps" "$MODEL_ROOT"

stop_pid() {
  local pid="$1"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "正在停止旧 H3 API，PID=$pid"
    kill "$pid" || true
    for _ in $(seq 1 30); do
      if ! kill -0 "$pid" 2>/dev/null; then
        return 0
      fi
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "旧服务未正常退出，发送 SIGKILL。"
      kill -9 "$pid" || true
    fi
  fi
}

# 先按旧 PID 文件停止。
if [[ -f "$OLD_H3/api.pid" ]]; then
  stop_pid "$(cat "$OLD_H3/api.pid" 2>/dev/null || true)"
fi

# PID 文件可能过期或缺失，再按旧服务的完整命令行兜底查找。
while read -r OLD_PID; do
  [[ -n "$OLD_PID" ]] && stop_pid "$OLD_PID"
done < <(
  pgrep -f "^${OLD_H3}/venv/bin/python -m uvicorn api_server:app .*--port 6006( |$)" || true
)

if pgrep -f "^${OLD_H3}/venv/bin/python -m uvicorn api_server:app .*--port 6006( |$)" >/dev/null 2>&1; then
  echo "旧 6006 服务仍在运行，停止迁移以避免破坏正在运行的环境。"
  exit 1
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
DIFFSYNTH_PATH="$ROOT/.deps/DiffSynth-Studio"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "没有找到可用的 Python 环境，请执行 bash scripts/install.sh。"
  exit 1
fi
if [[ ! -d "$DIFFSYNTH_PATH/diffsynth" ]]; then
  echo "迁移后没有找到 DiffSynth-Studio：$DIFFSYNTH_PATH"
  exit 1
fi

export PYTHONPATH="$ROOT:$DIFFSYNTH_PATH${PYTHONPATH:+:$PYTHONPATH}"

echo "正在重新绑定 DiffSynth editable install 到新路径。"
"$PYTHON_BIN" -m pip install -e "$DIFFSYNTH_PATH"
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
echo "DiffSynth 已整理到：$DIFFSYNTH_PATH"
echo ""
echo "Krea 2 已准备完成的话，下一步直接执行："
echo "bash scripts/start.sh"
echo "bash scripts/healthcheck.sh"
