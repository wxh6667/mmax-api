#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

H3_DIT="/root/autodl-tmp/models/h3/DiffSynth-Studio/MiniMax-H3-NF4/minimax-h3-fl2va-pruned-nf4.safetensors"
KREA_DIT="/root/autodl-tmp/models/krea2/krea2_turbo_bf16.safetensors"
KREA_TEXT="/root/autodl-tmp/models/krea2/qwen3vl_4b_bf16.safetensors"
KREA_VAE="/root/autodl-tmp/models/krea2/qwen_image/vae/diffusion_pytorch_model.safetensors"

for path in "$H3_DIT" "$KREA_DIT" "$KREA_TEXT" "$KREA_VAE" "$ROOT/.venv/bin/python" "$ROOT/.deps/DiffSynth-Studio/diffsynth"; do
  if [[ ! -e "$path" ]]; then
    echo "尚未满足清理条件，缺少：$path"
    exit 1
  fi
done

if [[ -d /root/autodl-tmp/h3 ]]; then
  echo "删除旧 H3 残留目录：/root/autodl-tmp/h3"
  rm -rf /root/autodl-tmp/h3
fi

if [[ -d /root/autodl-tmp/imagegen/ComfyUI ]]; then
  echo "删除旧 ComfyUI：/root/autodl-tmp/imagegen/ComfyUI"
  rm -rf /root/autodl-tmp/imagegen/ComfyUI
fi

if [[ -d /root/autodl-tmp/imagegen ]] && [[ -z "$(find /root/autodl-tmp/imagegen -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  rmdir /root/autodl-tmp/imagegen
fi

echo "旧服务和 ComfyUI 残留已清理。"
