#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[env] Created .env from template."
fi

if [[ ! -f .api_key && -f /root/autodl-tmp/h3/.api_key ]]; then
  cp /root/autodl-tmp/h3/.api_key .api_key
  chmod 600 .api_key
  echo "[env] Copied API Key from legacy H3 service."
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON_BIN="${MMAX_PYTHON_BIN:-$ROOT/.venv/bin/python}"
DIFFSYNTH_PATH="${MMAX_DIFFSYNTH_PATH:-$ROOT/.deps/DiffSynth-Studio}"
DATA_DIR="${MMAX_DATA_DIR:-/root/autodl-tmp}"

# 数据盘守卫：模型权重与 outputs 都落在数据盘（默认 /root/autodl-tmp）。
# 若该路径不是独立挂载点，说明数据盘未挂载，继续会把 ≈28GB 权重静默写进 30G 系统盘。
# 判定依据是"是否为挂载点"而非"目录是否存在"——目录可能正是被脚本自己 mkdir 出来的。
is_mountpoint() {
  local target="$1"
  if command -v mountpoint >/dev/null 2>&1; then
    if mountpoint -q "$target" 2>/dev/null; then return 0; fi
  fi
  if command -v findmnt >/dev/null 2>&1; then
    if findmnt --mountpoint "$target" >/dev/null 2>&1; then return 0; fi
  fi
  # 可移植回退：按 /proc/mounts 第二列精确匹配，避免子串误判。
  local real
  real="$(readlink -f "$target" 2>/dev/null || true)"
  if [[ -n "$real" ]] && awk -v t="$real" '$2 == t { found = 1 } END { exit !found }' /proc/mounts 2>/dev/null; then
    return 0
  fi
  return 1
}

if [[ "${MMAX_ALLOW_NO_DATA_DISK:-0}" == "1" ]]; then
  echo "[disk] MMAX_ALLOW_NO_DATA_DISK=1：跳过数据盘挂载检查（$DATA_DIR）。"
elif is_mountpoint "$DATA_DIR"; then
  echo "[disk] Data disk mounted at $DATA_DIR."
else
  echo "[disk] ERROR: data disk not mounted at $DATA_DIR (not a mountpoint)." >&2
  echo "[disk] 错误：数据盘未挂载，继续会把模型权重（≈28GB）与 outputs 写入系统盘（30G），可能写满系统盘。" >&2
  echo "[disk] 请先挂载数据盘（AutoDL 控制台开启数据盘），或把 MMAX_DATA_DIR 指向已挂载的数据盘。" >&2
  echo "[disk] 确知要用系统盘或处于非 AutoDL 环境，可设 MMAX_ALLOW_NO_DATA_DISK=1 跳过此检查。" >&2
  exit 1
fi

# AutoDL 学术资源加速仅代理 GitHub / HuggingFace 四个域名，
# PyPI 与魔搭（ModelScope）国内直连更快，因此用完立即关闭，避免拖慢后续下载。
accel_on() {
  if [[ -f /etc/network_turbo ]]; then
    # shellcheck disable=SC1091
    source /etc/network_turbo
    echo "[net] AutoDL network turbo ON (GitHub/HF only)."
    return 0
  fi
  return 1
}

accel_off() {
  unset http_proxy https_proxy
  echo "[net] network turbo OFF."
}

VENV_FRESH=0
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[venv] Creating .venv ..."
  python3 -m venv "$ROOT/.venv"
  PYTHON_BIN="$ROOT/.venv/bin/python"
  VENV_FRESH=1
fi

# 工具链升级只在新装 venv 时执行，重复运行 install.sh 不再重复升级。
if [[ "$VENV_FRESH" -eq 1 ]]; then
  "$PYTHON_BIN" -m pip install --no-cache-dir -U pip setuptools wheel
fi

if [[ ! -d "$DIFFSYNTH_PATH/.git" ]]; then
  echo "[deps] Fetching DiffSynth-Studio ..."
  mkdir -p "$(dirname "$DIFFSYNTH_PATH")"
  accel_on || true
  # 浅克隆减小传输量；加速通道不稳（官方不承诺稳定）失败时回退 PyPI 包。
  if ! git clone --depth 1 https://github.com/modelscope/DiffSynth-Studio.git "$DIFFSYNTH_PATH"; then
    rm -rf "$DIFFSYNTH_PATH"
    echo "[deps] GitHub clone failed, falling back to PyPI package 'diffsynth'."
  fi
  accel_off
fi

# 大依赖（torch + CUDA wheels ≈3.6GB）禁用 pip 缓存：既不在系统盘留 wheel 残渣，
# 中途失败也不会残留半包；依赖最终解包进 $PYTHON_BIN 的 venv。
if [[ -d "$DIFFSYNTH_PATH/diffsynth" ]]; then
  "$PYTHON_BIN" -m pip install --no-cache-dir -e "$DIFFSYNTH_PATH"
else
  "$PYTHON_BIN" -m pip install --no-cache-dir diffsynth
fi
"$PYTHON_BIN" -m pip install --no-cache-dir -e "$ROOT"

# 魔搭（modelscope）是模型权重的下载通道，已装则复用。
"$PYTHON_BIN" -c "import modelscope" 2>/dev/null || "$PYTHON_BIN" -m pip install --no-cache-dir modelscope

mkdir -p runtime "$DATA_DIR/outputs/videos" "$DATA_DIR/outputs/images" "$DATA_DIR/models"

# 初次部署自动生成 API Key（已存在则保留）；服务端无 Key 时所有请求会 500。
KEY_FILE="${MMAX_API_KEY_FILE:-/root/autodl-tmp/mmax/.api_key}"
if [[ ! -s "$KEY_FILE" ]]; then
  mkdir -p "$(dirname "$KEY_FILE")"
  openssl rand -hex 24 > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  echo "[auth] API Key generated: $(cat "$KEY_FILE")"
fi

# 模型权重走魔搭国内 CDN 幂等下载（不需要代理，务必在 accel_off 之后执行）；
# 文件齐全时自动跳过，MMAX_SKIP_MODEL_DOWNLOAD=1 可整体跳过。
if [[ "${MMAX_SKIP_MODEL_DOWNLOAD:-0}" == "1" ]]; then
  echo "[models] Skipped (MMAX_SKIP_MODEL_DOWNLOAD=1)."
else
  "$PYTHON_BIN" - <<'PY'
from pathlib import Path

from mmax_api.config import settings
from modelscope import snapshot_download

nf4_dir = Path(settings.h3_dit).parent
nf4_files = [
    settings.h3_dit,
    settings.h3_text_encoder,
    settings.h3_video_vae,
    settings.h3_audio_vae,
]

if all(Path(p).is_file() for p in nf4_files):
    print(f"[models] H3 NF4 weights complete, skip: {nf4_dir}")
else:
    print(f"[models] Downloading H3 NF4 weights to {nf4_dir} ...")
    # 只下 mmax 实际使用的 4 个文件；整仓还有 ref2va / 未剪枝等未用权重，
    # 无过滤会整仓拉 ≈72.5GB，这里过滤后仅 ≈27.7GB。
    snapshot_download(
        "DiffSynth-Studio/MiniMax-H3-NF4",
        allow_patterns=[Path(p).name for p in nf4_files],
        local_dir=str(nf4_dir),
    )
    print("[models] H3 NF4 weights done.")

processor_dir = Path(settings.h3_processor)
h3_root = processor_dir.parent.parent  # .../MiniMax-H3
if processor_dir.is_dir() and any(processor_dir.iterdir()):
    print(f"[models] H3 processor ready, skip: {processor_dir}")
else:
    print(f"[models] Downloading H3 processor to {h3_root} ...")
    snapshot_download(
        "MiniMax/MiniMax-H3",
        allow_patterns=["FL2VA/processor/*"],
        local_dir=str(h3_root),
    )
    print("[models] H3 processor done.")
PY
fi

if ! ls "${MMAX_HIDREAM_DIR:-/root/autodl-tmp/models/hidream-o1-image}"/model-*.safetensors >/dev/null 2>&1; then
  echo "[models] Note: HiDream image model not found (${MMAX_HIDREAM_DIR:-/root/autodl-tmp/models/hidream-o1-image}/model-*.safetensors); image API stays not-ready until you place it."
fi

# 兜底清理 pip wheel 缓存（默认在 /root/.cache/pip，属系统盘）：本脚本已用 --no-cache-dir，
# 这里再清一次，释放旧版本 install.sh 或基础镜像遗留的缓存（幂等，无缓存时删除 0 个文件）。
# 清理属尽力而为，不因此中断已完成的安装；但失败必须显式暴露，不能谎报成功。
if "$PYTHON_BIN" -m pip cache purge >/dev/null 2>&1; then
  echo "[pip] Wheel cache purged."
else
  echo "[pip] WARNING: pip cache purge failed; wheel cache may remain (see $PYTHON_BIN -m pip cache purge)." >&2
fi

echo "INSTALL DONE."
echo "Python: $PYTHON_BIN"
echo "DiffSynth: $DIFFSYNTH_PATH"
