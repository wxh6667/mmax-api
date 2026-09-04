#!/usr/bin/env python3
import json
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from safetensors import safe_open
from safetensors.torch import save_file


SRC_DIT = Path("/root/autodl-tmp/imagegen/ComfyUI/models/diffusion_models/krea2_turbo_fp8_scaled.safetensors")
SRC_TEXT = Path("/root/autodl-tmp/imagegen/ComfyUI/models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors")
OUT_DIR = Path("/root/autodl-tmp/models/krea2")
OUT_DIT = OUT_DIR / "krea2_turbo_bf16.safetensors"
OUT_TEXT = OUT_DIR / "qwen3vl_4b_bf16.safetensors"
TOKENIZER_DIR = OUT_DIR / "qwen3vl_tokenizer"
QWEN_IMAGE_DIR = OUT_DIR / "qwen_image"


def _read_marker(tensor: torch.Tensor) -> dict:
    raw = bytes(tensor.to(torch.uint8).tolist()).decode("utf-8")
    return json.loads(raw)


def _quant_layers(path: Path) -> dict[str, dict]:
    layers: dict[str, dict] = {}
    with safe_open(str(path), framework="pt", device="cpu") as f:
        metadata = f.metadata() or {}
        if "_quantization_metadata" in metadata:
            info = json.loads(metadata["_quantization_metadata"])
            layers.update(info.get("layers", {}))
        for key in f.keys():
            if key.endswith(".comfy_quant"):
                layer = key[: -len(".comfy_quant")]
                layers[layer] = _read_marker(f.get_tensor(key))
    return layers


def convert_fp8_to_bf16(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)

    print(f"\n===== 转换 {src.name} =====")
    quant_layers = _quant_layers(src)
    print(f"检测到量化层：{len(quant_layers)}")

    output: dict[str, torch.Tensor] = {}
    with safe_open(str(src), framework="pt", device="cpu") as f:
        keys = list(f.keys())
        for index, key in enumerate(keys, start=1):
            if key.endswith(".comfy_quant") or key.endswith(".weight_scale") or key.endswith(".input_scale"):
                continue

            tensor = f.get_tensor(key)
            if key.endswith(".weight"):
                layer = key[: -len(".weight")]
                marker = quant_layers.get(layer)
                if marker and marker.get("format") == "float8_e4m3fn":
                    scale_key = f"{layer}.weight_scale"
                    if scale_key not in keys:
                        raise RuntimeError(f"量化层缺少 weight_scale：{layer}")
                    scale = f.get_tensor(scale_key).to(torch.bfloat16)
                    tensor = tensor.to(torch.bfloat16) * scale
                elif tensor.is_floating_point() and tensor.dtype != torch.bfloat16:
                    tensor = tensor.to(torch.bfloat16)
            elif tensor.is_floating_point() and tensor.dtype in {torch.float16, torch.float32, torch.float64}:
                tensor = tensor.to(torch.bfloat16)

            output[key] = tensor.contiguous()
            if index % 100 == 0 or index == len(keys):
                print(f"已处理 {index}/{len(keys)} 个 tensor")

    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"正在写入：{dst}")
    save_file(output, str(dst), metadata={"format": "pt", "converted_by": "mmax-api"})
    print(f"转换完成：{dst.stat().st_size / 1024**3:.2f} GiB")


def download_small_components() -> None:
    print("\n===== 下载 Qwen3-VL tokenizer/config =====")
    snapshot_download(
        repo_id="Qwen/Qwen3-VL-4B-Instruct",
        local_dir=str(TOKENIZER_DIR),
        allow_patterns=[
            "*.json", "*.txt", "*.model", "tokenizer*", "vocab*", "merges*", "chat_template*"
        ],
    )

    print("\n===== 下载官方 Qwen Image VAE =====")
    snapshot_download(
        repo_id="Qwen/Qwen-Image",
        local_dir=str(QWEN_IMAGE_DIR),
        allow_patterns=[
            "vae/config.json",
            "vae/diffusion_pytorch_model.safetensors",
        ],
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if OUT_DIT.exists():
        print(f"已存在，跳过 Krea DiT 转换：{OUT_DIT}")
    else:
        convert_fp8_to_bf16(SRC_DIT, OUT_DIT)

    if OUT_TEXT.exists():
        print(f"已存在，跳过 Qwen3-VL 转换：{OUT_TEXT}")
    else:
        convert_fp8_to_bf16(SRC_TEXT, OUT_TEXT)

    download_small_components()

    print("\n===== Krea 2 准备完成 =====")
    print(f"DiT: {OUT_DIT}")
    print(f"Text Encoder: {OUT_TEXT}")
    print(f"Tokenizer: {TOKENIZER_DIR}")
    print(f"VAE: {QWEN_IMAGE_DIR / 'vae/diffusion_pytorch_model.safetensors'}")


if __name__ == "__main__":
    main()
