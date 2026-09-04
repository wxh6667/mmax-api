from pathlib import Path

import torch

from .base import Backend
from ..config import settings
from ..jobs import jobs


class Krea2Backend(Backend):
    """Krea 2 Turbo 图片后端。模型采用本地 BF16 文件，运行时不依赖 ComfyUI。"""

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
                # 当前服务器使用的是 ComfyUI 打包后的 Qwen3-VL 文本编码器，
                # 其键名省略了官方 checkpoint 中的 language_model 层级。
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

        # 本项目把 ComfyUI FP8 权重一次性转换成普通 BF16 checkpoint。
        # 对这类自定义 hash + state_dict converter 的本地文件，使用 disk offload
        # 会触发 DiffSynth disk_map 的重命名映射问题，因此 Krea 统一改用 CPU RAM
        # 作为 offload 层。服务器拥有充足系统内存，GPU 侧仍由 DiffSynth 按需搬运。
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

    def generate(self, job_id: str, payload: dict) -> str:
        pipe = self._load()
        width = int(payload["width"])
        height = int(payload["height"])
        seed = payload.get("seed")

        print(f"[Krea] {job_id} 开始生成：{width}x{height}", flush=True)
        jobs.update(job_id, progress=5)
        image = pipe(
            prompt=payload["prompt"],
            seed=seed,
            height=height,
            width=width,
            num_inference_steps=8,
            cfg_scale=1,
            mu=1.15,
        )
        jobs.update(job_id, progress=95)

        output_path = settings.output_dir / "images" / f"{job_id}.png"
        image.save(output_path, format="PNG")
        print(f"[Krea] {job_id} 生成完成：{output_path}", flush=True)
        return str(output_path)


krea2_backend = Krea2Backend()
