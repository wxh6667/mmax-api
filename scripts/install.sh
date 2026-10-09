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

# AutoDL 学术资源加速仅代理 GitHub / HuggingFace 四个域名，
# PyPI 与魔搭（ModelScope）国内直连更快，因此用完立即关闭，避免拖慢后续下载。
accel_on() {
  if [[ -f /etc/network_turbo ]]; then
    # shellcheck disable=SC1091
    source /etc/network_turbo
    echo "已启用 AutoDL 学术资源加速（GitHub）。"
    return 0
  fi
  return 1
}

accel_off() {
  unset http_proxy https_proxy
}

VENV_FRESH=0
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "未找到独立 Python 环境，正在创建 .venv。"
  python3 -m venv "$ROOT/.venv"
  PYTHON_BIN="$ROOT/.venv/bin/python"
  VENV_FRESH=1
fi

# 工具链升级只在新装 venv 时执行，重复运行 install.sh 不再重复升级。
if [[ "$VENV_FRESH" -eq 1 ]]; then
  "$PYTHON_BIN" -m pip install -U pip setuptools wheel
fi

if [[ ! -d "$DIFFSYNTH_PATH/.git" ]]; then
  echo "正在获取 DiffSynth-Studio。"
  mkdir -p "$(dirname "$DIFFSYNTH_PATH")"
  accel_on || true
  # 浅克隆减小传输量；加速通道不稳（官方不承诺稳定）失败时回退 PyPI 包。
  if ! git clone --depth 1 https://github.com/modelscope/DiffSynth-Studio.git "$DIFFSYNTH_PATH"; then
    rm -rf "$DIFFSYNTH_PATH"
    echo "GitHub 克隆失败，将改用 PyPI 安装 diffsynth。"
  fi
  accel_off
fi

if [[ -d "$DIFFSYNTH_PATH/diffsynth" ]]; then
  "$PYTHON_BIN" -m pip install -e "$DIFFSYNTH_PATH"
else
  "$PYTHON_BIN" -m pip install diffsynth
fi
"$PYTHON_BIN" -m pip install -e "$ROOT"

# 魔搭（modelscope）是模型权重的下载通道，已装则复用。
"$PYTHON_BIN" -c "import modelscope" 2>/dev/null || "$PYTHON_BIN" -m pip install modelscope

mkdir -p runtime /root/autodl-tmp/outputs/videos /root/autodl-tmp/outputs/images /root/autodl-tmp/models

# 初次部署自动生成 API Key（已存在则保留）；服务端无 Key 时所有请求会 500。
KEY_FILE="${MMAX_API_KEY_FILE:-/root/autodl-tmp/mmax/.api_key}"
if [[ ! -s "$KEY_FILE" ]]; then
  mkdir -p "$(dirname "$KEY_FILE")"
  openssl rand -hex 24 > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  echo "已生成 API Key：$(cat "$KEY_FILE")"
fi

# 模型权重走魔搭国内 CDN 幂等下载（不需要代理，务必在 accel_off 之后执行）；
# 文件齐全时自动跳过，MMAX_SKIP_MODEL_DOWNLOAD=1 可整体跳过。
if [[ "${MMAX_SKIP_MODEL_DOWNLOAD:-0}" == "1" ]]; then
  echo "已按 MMAX_SKIP_MODEL_DOWNLOAD=1 跳过模型下载。"
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
    print(f"H3 NF4 权重已齐全，跳过下载：{nf4_dir}")
else:
    print(f"正在从魔搭下载 H3 NF4 权重到 {nf4_dir} ...")
    snapshot_download("DiffSynth-Studio/MiniMax-H3-NF4", local_dir=str(nf4_dir))
    print("H3 NF4 权重下载完成。")

processor_dir = Path(settings.h3_processor)
h3_root = processor_dir.parent.parent  # .../MiniMax-H3
if processor_dir.is_dir() and any(processor_dir.iterdir()):
    print(f"H3 processor 已就绪，跳过下载：{processor_dir}")
else:
    print(f"正在从魔搭下载 H3 processor 到 {h3_root} ...")
    snapshot_download(
        "MiniMax/MiniMax-H3",
        allow_patterns=["FL2VA/processor/*"],
        local_dir=str(h3_root),
    )
    print("H3 processor 下载完成。")
PY
fi

if ! ls "${MMAX_HIDREAM_DIR:-/root/autodl-tmp/models/hidream-o1-image}"/model-*.safetensors >/dev/null 2>&1; then
  echo "提示：未检测到 HiDream 图片模型（\${MMAX_HIDREAM_DIR}/model-*.safetensors），如需图片能力请手动放置。"
fi

echo "安装完成。"
echo "Python：$PYTHON_BIN"
echo "DiffSynth：$DIFFSYNTH_PATH"
