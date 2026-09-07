from glob import glob
from pathlib import Path

import torch

from .base import Backend
from ..config import settings
from ..jobs import jobs


class QwenImage2512Backend(Backend):
    """Qwen-Image-2512 文生图后端。

    4090D 只有 24GB 显存，但服务器内存充足，因此使用 FP8 CPU offload、
    BF16 GPU 计算，避免额外占用宝贵的数据盘做 disk offload。
    """

    kind = "image"

    def __init__(self) -> None:
        self.model_id = settings.qwen_image_model_id
        self._pipe = None

    def _transformer_files(self) -> list[str]:
        return sorted(glob(str(settings.qwen_image_dir / "transformer" / "diffusion_pytorch_model*.safetensors")))

    def _text_encoder_files(self) -> list[str]:
        return sorted(glob(str(settings.qwen_image_dir / "text_encoder" / "model*.safetensors")))

    @property
    def _vae_file(self) -> Path:
        return settings.qwen_image_dir / "vae" / "diffusion_pytorch_model.safetensors"

    @property
    def _tokenizer_dir(self) -> Path:
        return settings.qwen_image_dir / "tokenizer"

    def ready(self) -> tuple[bool, str | None]:
        if not settings.qwen_image_enabled:
            return False, "Qwen-Image-2512 已在配置中关闭"

        missing = []
        if not self._transformer_files():
            missing.append(str(settings.qwen_image_dir / "transformer" / "diffusion_pytorch_model*.safetensors"))
        if not self._text_encoder_files():
            missing.append(str(settings.qwen_image_dir / "text_encoder" / "model*.safetensors"))
        if not self._vae_file.exists():
            missing.append(str(self._vae_file))
        if not self._tokenizer_dir.exists():
            missing.append(str(self._tokenizer_dir))

        if missing:
            return False, "缺少模型文件：" + ", ".join(missing)
        return True, None

    def _load(self):
        if self._pipe is not None:
            return self._pipe

        ok, reason = self.ready()
        if not ok:
            raise RuntimeError(reason)

        from diffsynth.pipelines.qwen_image import QwenImagePipeline, ModelConfig

        print("===== 正在加载 Qwen-Image-2512 =====", flush=True)
        vram_config = {
            "offload_dtype": torch.float8_e4m3fn,
            "offload_device": "cpu",
            "onload_dtype": torch.float8_e4m3fn,
            "onload_device": "cpu",
            "preparing_dtype": torch.float8_e4m3fn,
            "preparing_device": "cuda",
            "computation_dtype": torch.bfloat16,
            "computation_device": "cuda",
        }
        total_gb = torch.cuda.mem_get_info("cuda")[1] / (1024 ** 3)
        self._pipe = QwenImagePipeline.from_pretrained(
            torch_dtype=torch.bfloat16,
            device="cuda",
            model_configs=[
                ModelConfig(path=self._transformer_files(), **vram_config),
                ModelConfig(path=self._text_encoder_files(), **vram_config),
                ModelConfig(path=str(self._vae_file), **vram_config),
            ],
            tokenizer_config=ModelConfig(path=str(self._tokenizer_dir)),
            vram_limit=max(1.0, total_gb - settings.qwen_image_vram_reserve_gb),
        )
        print("===== Qwen-Image-2512 加载完成 =====", flush=True)
        return self._pipe

    def generate(self, job_id: str, payload: dict) -> str:
        pipe = self._load()
        width = int(payload["width"])
        height = int(payload["height"])
        steps = int(payload.get("steps") or settings.qwen_image_steps)
        cfg_scale = float(payload.get("cfg_scale") or settings.qwen_image_cfg_scale)
        seed = payload.get("seed")

        print(
            f"[Qwen-Image] {job_id} 开始生成：{width}x{height}，"
            f"{steps} steps，CFG={cfg_scale:g}",
            flush=True,
        )
        jobs.update(job_id, progress=5)

        image = pipe(
            prompt=payload["prompt"],
            negative_prompt=payload.get("negative_prompt") or "",
            width=width,
            height=height,
            seed=seed,
            num_inference_steps=steps,
            cfg_scale=cfg_scale,
            tiled=settings.qwen_image_vae_tiled,
            tile_size=settings.qwen_image_tile_size,
            tile_stride=settings.qwen_image_tile_stride,
        )
        jobs.update(job_id, progress=95)

        output_path = settings.output_dir / "images" / f"{job_id}.png"
        image.save(output_path, format="PNG")
        pipe.load_models_to_device([])

        print(f"[Qwen-Image] {job_id} 生成完成：{output_path}", flush=True)
        return str(output_path)


qwen_image_backend = QwenImage2512Backend()
