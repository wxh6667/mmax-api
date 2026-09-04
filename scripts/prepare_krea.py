#!/usr/bin/env python3
import json
from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import save_file

try:
    from modelscope import snapshot_download as ms_snapshot_download
except Exception:
    ms_snapshot_download = None

try:
    from huggingface_hub import snapshot_download as hf_snapshot_download
except Exception:
    hf_snapshot_download = None


SRC_DIT = Path("/root/autodl-tmp/imagegen/ComfyUI/models/diffusion_models/krea2_turbo_fp8_scaled.safetensors")
SRC_TEXT = Path("/root/autodl-tmp/imagegen/ComfyUI/models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors")
OUT_DIR = Path("/root/autodl-tmp/models/krea2")
OUT_DIT = OUT_DIR / "krea2_turbo_bf16.safetensors"
OUT_TEXT = OUT_DIR / "qwen3vl_4b_bf16.safetensors"
TOKENIZER_DIR = OUT_DIR / "qwen3vl_tokenizer"
QWEN_IMAGE_DIR = OUT_DIR / "qwen_image"
VAE_FILE = QWEN_IMAGE_DIR / "vae/diffusion_pytorch_model.safetensors"


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


def _download_repo_files(model_id: str, local_dir: Path, patterns: list[str]) -> None:
    """优先使用 ModelScope，失败时再尝试 Hugging Face。"""
    errors: list[str] = []
    local_dir.mkdir(parents=True, exist_ok=True)

    if ms_snapshot_download is not None:
        try:
            print(f"使用 ModelScope：{model_id}")
            ms_snapshot_download(
                model_id=model_id,
                local_dir=str(local_dir),
                allow_file_pattern=patterns,
            )
            return
        except Exception as exc:
            errors.append(f"ModelScope: {type(exc).__name__}: {exc}")
            print(f"ModelScope 下载失败，将尝试 Hugging Face：{exc}")

    if hf_snapshot_download is not None:
        try:
            print(f"使用 Hugging Face：{model_id}")
            hf_snapshot_download(
                repo_id=model_id,
                local_dir=str(local_dir),
                allow_patterns=patterns,
            )
            return
        except Exception as exc:
            errors.append(f"Hugging Face: {type(exc).__name__}: {exc}")

    detail = "\n".join(errors) if errors else "没有可用的模型下载客户端。"
    raise RuntimeError(f"无法下载 {model_id}：\n{detail}")


def download_small_components() -> None:
    print("\n===== 下载 Qwen3-VL tokenizer/config =====")
    tokenizer_config = TOKENIZER_DIR / "tokenizer_config.json"
    if tokenizer_config.exists():
        print(f"已存在，跳过 tokenizer 下载：{TOKENIZER_DIR}")
    else:
        _download_repo_files(
            model_id="Qwen/Qwen3-VL-4B-Instruct",
            local_dir=TOKENIZER_DIR,
            patterns=[
                "*.json",
                "*.txt",
                "*.model",
                "tokenizer*",
                "vocab*",
                "merges*",
                "chat_template*",
            ],
        )

    print("\n===== 下载官方 Qwen Image VAE =====")
    if VAE_FILE.exists():
        print(f"已存在，跳过 VAE 下载：{VAE_FILE}")
    else:
        _download_repo_files(
            model_id="Qwen/Qwen-Image",
            local_dir=QWEN_IMAGE_DIR,
            patterns=[
                "vae/config.json",
                "vae/diffusion_pytorch_model.safetensors",
            ],
        )

    if not tokenizer_config.exists():
        raise RuntimeError(f"tokenizer 下载后仍缺少：{tokenizer_config}")
    if not VAE_FILE.exists():
        raise RuntimeError(f"VAE 下载后仍缺少：{VAE_FILE}")


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
    print(f"VAE: {VAE_FILE}")


if __name__ == "__main__":
    main()
