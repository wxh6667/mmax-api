from pathlib import Path

import torch
from PIL import Image, ImageOps

from .base import Backend
from ..config import settings
from ..jobs import jobs


class Krea2Backend(Backend):
    """Krea 2 Turbo 图片后端，支持文生图和单参考图编辑。"""

    kind = "image"

    def __init__(self) -> None:
        self.model_id = settings.krea_model_id
        self._pipe = None
        self._registered = False

    def _paths(self) -> list[Path]:
        return [settings.krea_dit, settings.krea_text_encoder, settings.krea_vae, settings.krea_tokenizer]

    def ready(self) -> tuple[bool, str | None]:
        if not settings.krea_enabled:
            return False, "Krea 2 已在配置中关闭"
        missing = [str(path) for path in self._paths() if not path.exists()]
        if missing:
            return False, "缺少模型文件：" + ", ".join(missing)
        return True, None

    def _register_local_models(self) -> None:
        """把本地转换后的 checkpoint hash 动态注册到 DiffSynth loader。"""
        if self._registered:
            return

        import diffsynth.configs as configs
        import diffsynth.models.model_loader as model_loader
        from diffsynth.core.loader import hash_model_file

        entries = (
            {
                "model_hash": hash_model_file(str(settings.krea_dit)),
                "model_name": "krea2_dit",
                "model_class": "diffsynth.models.krea2_dit.SingleStreamDiT",
                "state_dict_converter": "diffsynth.utils.state_dict_converters.krea2_dit.Krea2DiTStateDictConverter",
            },
            {
                "model_hash": hash_model_file(str(settings.krea_text_encoder)),
                "model_name": "krea2_text_encoder",
                "model_class": "diffsynth.models.krea2_text_encoder.Krea2TextEncoder",
                "state_dict_converter": "mmax_api.state_dict_converters.Krea2ComfyTextEncoderStateDictConverter",
            },
            {
                "model_hash": hash_model_file(str(settings.krea_vae)),
                "model_name": "qwen_image_vae",
                "model_class": "diffsynth.models.qwen_image_vae.QwenImageVAE",
            },
        )

        existing = tuple(configs.MODEL_CONFIGS)
        existing_pairs = {(item.get("model_hash"), item.get("model_name")) for item in existing}
        additions = tuple(
            item for item in entries
            if (item["model_hash"], item["model_name"]) not in existing_pairs
        )
        if additions:
            merged = existing + additions
            configs.MODEL_CONFIGS = merged
            model_loader.MODEL_CONFIGS = merged
        self._registered = True

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        ok, reason = self.ready()
        if not ok:
            raise RuntimeError(reason)

        self._register_local_models()
        from diffsynth.pipelines.krea2 import Krea2Pipeline, ModelConfig

        print("===== 正在加载 Krea 2 Turbo =====", flush=True)

        # Krea 的本地 BF16 checkpoint 使用 CPU RAM offload。
        # 这样 state_dict converter 会先完成键名转换，再交给显存管理模块。
        vram_config = {
            "offload_dtype": torch.bfloat16,
            "offload_device": "cpu",
            "onload_dtype": torch.bfloat16,
            "onload_device": "cpu",
            "preparing_dtype": torch.bfloat16,
            "preparing_device": "cuda",
            "computation_dtype": torch.bfloat16,
            "computation_device": "cuda",
        }
        total_gb = torch.cuda.mem_get_info("cuda")[1] / (1024 ** 3)
        self._pipe = Krea2Pipeline.from_pretrained(
            torch_dtype=torch.bfloat16,
            device="cuda",
            model_configs=[
                ModelConfig(path=str(settings.krea_dit), **vram_config),
                ModelConfig(path=str(settings.krea_text_encoder), **vram_config),
                ModelConfig(path=str(settings.krea_vae), **vram_config),
            ],
            tokenizer_config=ModelConfig(path=str(settings.krea_tokenizer)),
            vram_limit=max(1.0, total_gb - settings.krea_vram_reserve_gb),
        )
        print("===== Krea 2 Turbo 加载完成 =====", flush=True)
        return self._pipe

    @staticmethod
    @torch.no_grad()
    def _infer(pipe, *, prompt: str, seed: int | None, height: int, width: int,
               input_image: Image.Image | None, strength: float) -> Image.Image:
        """运行 Krea2 原生计算链，并把上游尚未公开的 input_image 能力暴露出来。"""
        from tqdm import tqdm

        if input_image is not None:
            input_image = ImageOps.fit(
                input_image.convert("RGB"),
                (width, height),
                method=Image.Resampling.LANCZOS,
            )
        else:
            strength = 1.0

        pipe.scheduler.set_timesteps(
            8,
            denoising_strength=strength,
            dynamic_shift_len=(height // 16) * (width // 16),
            mu=1.15,
        )

        inputs_posi = {"prompt": prompt, "context_pre_compute": True}
        inputs_nega = {"negative_prompt": "", "context_pre_compute": True}
        inputs_shared = {
            "cfg_scale": 1,
            "height": height,
            "width": width,
            "seed": seed,
            "rand_device": "cpu",
            "num_inference_steps": 8,
            "input_image": input_image,
        }

        for unit in pipe.units:
            inputs_shared, inputs_posi, inputs_nega = pipe.unit_runner(
                unit, pipe, inputs_shared, inputs_posi, inputs_nega
            )

        pipe.load_models_to_device(pipe.in_iteration_models)
        models = {name: getattr(pipe, name) for name in pipe.in_iteration_models}
        for progress_id, timestep in enumerate(tqdm(pipe.scheduler.timesteps)):
            timestep = timestep.unsqueeze(0).to(dtype=pipe.torch_dtype, device=pipe.device)
            noise_pred = pipe.cfg_guided_model_fn(
                pipe.model_fn,
                1,
                inputs_shared,
                inputs_posi,
                inputs_nega,
                **models,
                timestep=timestep,
                progress_id=progress_id,
            )
            inputs_shared["latents"] = pipe.step(
                pipe.scheduler,
                progress_id=progress_id,
                noise_pred=noise_pred,
                **inputs_shared,
            )

        pipe.load_models_to_device(["vae"])
        image = pipe.vae.decode(inputs_shared["latents"])
        image = pipe.vae_output_to_image(image)
        pipe.load_models_to_device([])
        return image

    def generate(self, job_id: str, payload: dict) -> str:
        pipe = self._load()
        width = int(payload["width"])
        height = int(payload["height"])
        seed = payload.get("seed")
        input_image = payload.get("input_image")
        strength = float(payload.get("strength", 1.0))

        mode = "参考图编辑" if input_image is not None else "文生图"
        print(f"[Krea] {job_id} 开始{mode}：{width}x{height}, strength={strength:.2f}", flush=True)
        jobs.update(job_id, progress=5)
        image = self._infer(
            pipe,
            prompt=payload["prompt"],
            seed=seed,
            height=height,
            width=width,
            input_image=input_image,
            strength=strength,
        )
        jobs.update(job_id, progress=95)

        output_path = settings.output_dir / "images" / f"{job_id}.png"
        image.save(output_path, format="PNG")
        print(f"[Krea] {job_id} 生成完成：{output_path}", flush=True)
        return str(output_path)


krea2_backend = Krea2Backend()
