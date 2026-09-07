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
DIFFSYNTH_PATH="${MMAX_DIFFSYNTH_PATH:-$ROOT/.deps/DiffSynth-Studio}"
PORT="${MMAX_PORT:-6006}"
RUNTIME_DIR="${MMAX_RUNTIME_DIR:-$ROOT/runtime}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "找不到 Python：$PYTHON_BIN，请先执行 bash scripts/install.sh。"
  exit 1
fi
if [[ ! -d "$DIFFSYNTH_PATH/diffsynth" ]]; then
  echo "找不到 DiffSynth：$DIFFSYNTH_PATH，请先执行 bash scripts/install.sh。"
  exit 1
fi

mkdir -p "$RUNTIME_DIR"
PID_FILE="$RUNTIME_DIR/api.pid"
LOG_FILE="$RUNTIME_DIR/api.log"

is_mmax_pid() {
  local pid="$1"
  local cmdline
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  [[ -r "/proc/$pid/cmdline" ]] || return 1
  cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
  [[ "$cmdline" == *"-m mmax_api.run"* || "$cmdline" == *"uvicorn mmax_api.api:app"* ]]
}

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if is_mmax_pid "$PID"; then
    echo "服务已经在运行，PID=$PID"
    exit 0
  fi

  echo "检测到陈旧 PID 文件（PID=${PID:-未知}），可能来自关机或实例克隆，正在清理。"
  rm -f "$PID_FILE"
fi

# 即使 PID 文件丢失，也避免重复启动已有的 mmax-api 进程。
for proc in /proc/[0-9]*; do
  pid="${proc##*/}"
  if is_mmax_pid "$pid"; then
    echo "$pid" > "$PID_FILE"
    echo "发现已运行的 mmax-api，已恢复 PID 文件，PID=$pid"
    exit 0
  fi
done

export DIFFSYNTH_SKIP_DOWNLOAD=True
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export PYTHONPATH="$ROOT:$DIFFSYNTH_PATH${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

# mmax_api.run 会在导入 Uvicorn 前包装 stdout/stderr，
# 因此 Uvicorn、DiffSynth、模型后端和 traceback 都统一带北京时间。
nohup "$PYTHON_BIN" -m mmax_api.run >"$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "服务已启动，PID=$(cat "$PID_FILE")，端口：$PORT，日志：$LOG_FILE"
