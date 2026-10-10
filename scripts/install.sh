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

# ── 依赖安装策略（详见 .trellis/tasks/10-10-install-deps-fix/design.md）────────────
# H3 后端在 import 阶段即触发 av / torchaudio，二者属 diffsynth 的 [audio] extra（默认不装）；
# 裸装 diffsynth 会让服务能起、但第一条 H3 请求抛 ModuleNotFoundError。
DIFFSYNTH_EXTRAS="${MMAX_DIFFSYNTH_EXTRAS:-audio}"
# diffsynth 对 transformers 无上界，而其 transformers-5 兼容尚未收口（官方 nexusgen extra 自钉 4.49.0）。
DIFFSYNTH_CONSTRAINTS="${MMAX_DIFFSYNTH_CONSTRAINTS:-transformers<5}"
# 复用镜像自带 torch（venv --system-site-packages）：省 ≈3.6GB 下载，且 torch/CUDA 与镜像驱动天然匹配。
VENV_SYSTEM_SITE="${MMAX_VENV_SYSTEM_SITE:-1}"
# 安装期保留 pip 缓存（慢链路重试不必从零重下），成功后统一 purge。
PIP_CACHE_FLAG=""
if [[ "${MMAX_PIP_NO_CACHE:-0}" == "1" ]]; then
  PIP_CACHE_FLAG="--no-cache-dir"
fi

# [audio] extra 里的 torchaudio / torchcodec 对 torch 版本毫无保护，必须一并钉住：
#   - torchaudio 2.11.0 的 requires 是空的（它把 torch 钉版删了），pip 于是装上一个为 torch 2.11 /
#     CUDA 13 编译的版本，import 时报 "OSError: libcudart.so.13: cannot open shared object file"。
#   - torchcodec 所有版本都不声明 torch 依赖，且二者的配套关系无公式，只能查官方兼容表。
# 用户已在 MMAX_DIFFSYNTH_CONSTRAINTS 里钉了 torch 时，不再追加（否则 pip 直接冲突）。
# 正则放在变量里：`[=<>!~]` 直接写进 [[ =~ ]] 会被 bash 当成重定向/比较运算符而使脚本语法错误。
TORCH_PIN_RE='(^|[[:space:]])torch[[:space:]]*[=<>!~]'

# torchcodec 官方兼容表（https://github.com/pytorch/torchcodec#installing-torchcodec），按 torch 次版本查：
#   torch 2.7 -> 0.5 | 2.8 -> 0.7 | 2.9 -> 0.9 | 2.10 -> 0.10 | 2.11 -> 0.11
# 表里没有的 torch 版本返回空，调用方据此告警，而不是静默放行一个可能 ABI 不匹配的版本。
torchcodec_for() {
  case "$1" in
    2.7)  echo "0.5" ;;
    2.8)  echo "0.7" ;;
    2.9)  echo "0.9" ;;
    2.10) echo "0.10" ;;
    2.11) echo "0.11" ;;
    *)    echo "" ;;
  esac
}

if [[ "$VENV_SYSTEM_SITE" != "1" ]]; then
  echo "[deps] MMAX_VENV_SYSTEM_SITE=$VENV_SYSTEM_SITE: isolated venv; pip resolves and downloads torch itself (~3.6GB, slow)." >&2
else
  base_torch="$(python3 -c 'import torch;print(torch.__version__.split("+")[0])' 2>/dev/null || true)"
  if [[ -z "$base_torch" ]]; then
    echo "[deps] WARNING: no torch in base environment; pip will download the full torch (~3.6GB, slow)." >&2
  elif [[ "$DIFFSYNTH_CONSTRAINTS" =~ $TORCH_PIN_RE ]]; then
    echo "[deps] MMAX_DIFFSYNTH_CONSTRAINTS already pins torch; not adding torch==$base_torch."
  else
    torchcodec_ver="$(torchcodec_for "${base_torch%.*}")"
    DIFFSYNTH_CONSTRAINTS="$DIFFSYNTH_CONSTRAINTS torch==$base_torch torchaudio==$base_torch"
    if [[ -n "$torchcodec_ver" ]]; then
      DIFFSYNTH_CONSTRAINTS="$DIFFSYNTH_CONSTRAINTS torchcodec==$torchcodec_ver"
      echo "[deps] Reusing image torch $base_torch; also pinning torchaudio==$base_torch torchcodec==$torchcodec_ver."
    else
      echo "[deps] WARNING: base torch $base_torch is not in the torchcodec compatibility table." >&2
      echo "[deps] WARNING: torchcodec stays unpinned and may be ABI-incompatible with it." >&2
      echo "[deps] WARNING: add a '${base_torch%.*} -> <torchcodec>' entry to torchcodec_for() in this script." >&2
    fi
  fi
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
  if [[ "$VENV_SYSTEM_SITE" == "1" ]]; then
    python3 -m venv --system-site-packages "$ROOT/.venv"
  else
    python3 -m venv "$ROOT/.venv"
  fi
  PYTHON_BIN="$ROOT/.venv/bin/python"
  VENV_FRESH=1
else
  # system-site-packages 只在 venv 创建时确定，已存在的 venv 无法就地更改。
  want="false"
  if [[ "$VENV_SYSTEM_SITE" == "1" ]]; then
    want="true"
  fi
  have=""
  if [[ -f "$ROOT/.venv/pyvenv.cfg" ]]; then
    have="$(sed -n 's/^include-system-site-packages *= *//p' "$ROOT/.venv/pyvenv.cfg" | tail -n 1)"
  fi
  if [[ -n "$have" && "$have" != "$want" ]]; then
    echo "[venv] WARNING: existing .venv has include-system-site-packages=$have, expected $want." >&2
    echo "[venv] WARNING: this attribute cannot be changed in place; to reuse the image torch," >&2
    echo "[venv] WARNING: delete $ROOT/.venv and re-run this script (or set MMAX_VENV_SYSTEM_SITE=$have)." >&2
  fi
fi

# 工具链升级只在新装 venv 时执行，重复运行 install.sh 不再重复升级。
if [[ "$VENV_FRESH" -eq 1 ]]; then
  # shellcheck disable=SC2086
  "$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG -U pip setuptools wheel
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

# 大依赖（torch + CUDA wheels）安装期保留 pip 缓存：这条链路可能很慢，中途失败时已下好的
# wheel 可复用，不必从零重下；成功后再统一 purge（见脚本末尾），仍不留残渣。
# 必须带 [audio] extra：H3 后端顶层 import av / torchaudio，缺之则第一条 H3 请求即失败。
if [[ -d "$DIFFSYNTH_PATH/diffsynth" ]]; then
  # shellcheck disable=SC2086
  "$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG -e "${DIFFSYNTH_PATH}[${DIFFSYNTH_EXTRAS}]" $DIFFSYNTH_CONSTRAINTS
else
  # shellcheck disable=SC2086
  "$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG "diffsynth[${DIFFSYNTH_EXTRAS}]" $DIFFSYNTH_CONSTRAINTS
fi
# shellcheck disable=SC2086
"$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG -e "$ROOT"

# 魔搭（modelscope）是模型权重的下载通道，已装则复用。
# shellcheck disable=SC2086
"$PYTHON_BIN" -c "import modelscope" 2>/dev/null || "$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG modelscope

# 依赖冒烟校验：H3 依赖在 import 阶段即被触发，缺失必须在这里暴露，而不是等运行时第一条请求
# 才报 ModuleNotFoundError。刻意放在模型下载（≈28GB）之前——慢链路上先失败远比下完再失败划算。
# 无卡模式下 cuda=False 属预期，不作为失败条件；打印版本便于发现 --system-site-packages 的旧版本遮蔽。
#
# ffmpeg 二进制得单独查：mmax 的 H3 后处理直接 shell 调用它（mmax_api/backends/h3.py 里的 subprocess.run），
# 它不在任何 Python import 路径上，下面的 import 校验抓不到它。
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[verify] ERROR: ffmpeg not found on PATH; mmax's H3 post-processing shells out to it (mmax_api/backends/h3.py)." >&2
  echo "[verify] Install it (e.g. 'apt-get install -y ffmpeg') and re-run this script." >&2
  exit 1
fi
echo "[verify] ffmpeg: $(ffmpeg -version 2>/dev/null | head -n 1)"

if ! "$PYTHON_BIN" - <<'PY'
import importlib

for mod in ("torch", "torchvision", "torchaudio", "av", "torchcodec", "transformers", "fastapi", "uvicorn"):
    importlib.import_module(mod)
# torchaudio / torchcodec 与 torch 是 ABI 绑定的：版本错位（例如 torchcodec 为更高 CUDA 编译）必须在这里暴露。
# diffsynth 对 torchcodec 是函数内懒加载，只 import 管线根本触发不到它（这正是它曾漏过校验的原因），故显式取符号。
from torchcodec.decoders import AudioDecoder  # noqa: F401
from torchcodec.encoders import AudioEncoder  # noqa: F401
from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Pipeline  # noqa: F401

import fastapi
import torch
import torchaudio
import torchcodec
import torchvision
import transformers
import uvicorn

print(
    f"[verify] torch={torch.__version__} torchvision={torchvision.__version__} "
    f"torchaudio={torchaudio.__version__} torchcodec={torchcodec.__version__} "
    f"cuda={torch.cuda.is_available()} transformers={transformers.__version__} "
    f"fastapi={fastapi.__version__} uvicorn={uvicorn.__version__}"
)
PY
then
  echo "[verify] ERROR: dependencies incomplete (torch/torchvision/torchaudio/torchcodec/av/transformers/fastapi/uvicorn or the H3 pipeline failed to import)." >&2
  echo "[verify] Check the pip output above; if av/torchaudio/torchcodec are missing, confirm the diffsynth [${DIFFSYNTH_EXTRAS}] extra was installed." >&2
  exit 1
fi

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

# 兜底清理 pip wheel 缓存（默认在 /root/.cache/pip，属系统盘）：刻意放在最后一步，且只在冒烟校验
# 通过后才执行——校验失败时保留缓存，重试不必从零重下。释放本次下载的 wheel 与旧版 install.sh /
# 基础镜像遗留的缓存（幂等，无缓存时删除 0 个文件）。清理属尽力而为，不中断已完成的安装；失败显式暴露。
if "$PYTHON_BIN" -m pip cache purge >/dev/null 2>&1; then
  echo "[pip] Wheel cache purged."
else
  echo "[pip] WARNING: pip cache purge failed; wheel cache may remain (see $PYTHON_BIN -m pip cache purge)." >&2
fi

echo "INSTALL DONE."
echo "Python: $PYTHON_BIN"
echo "DiffSynth: $DIFFSYNTH_PATH"
