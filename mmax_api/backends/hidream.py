from glob import glob

import torch

from .base import Backend
from ..config import settings
from ..jobs import jobs


class HiDreamO1ImageBackend(Backend):
    """HiDream-O1-Image Full 图片后端。

    服务使用 DiffSynth 的显存管理：权重常驻 CPU，需要计算时按显存预算搬到 GPU，
    计算保持 BF16。这样既能在单卡环境稳定运行，也能在更大显存机器上自动利用更多显存。
    同一个 Full checkpoint 同时支持文生图、单图指令编辑和多参考主体驱动生成。
    """

    kind = "image"

    def __init__(self) -> None:
        self.model_id = settings.hidream_model_id
        self._pipe = None

    def _model_files(self) -> list[str]:
        return sorted(glob(str(settings.hidream_dir / "model-*.safetensors")))

    def ready(self) -> tuple[bool, str | None]:
        if not settings.hidream_enabled:
            return False, "HiDream-O1-Image 已在配置中关闭"
        if not settings.hidream_dir.exists():
            return False, f"模型目录不存在：{settings.hidream_dir}"
        if not self._model_files():
            return False, f"缺少模型文件：{settings.hidream_dir}/model-*.safetensors"
        return True, None

    def _load(self):
        if self._pipe is not None:
            return self._pipe

        ok, reason = self.ready()
        if not ok:
            raise RuntimeError(reason)

        from diffsynth.core.loader.config import ModelConfig
        from diffsynth.pipelines.hidream_o1_image import HiDreamO1ImagePipeline

        print("===== 正在加载 HiDream-O1-Image Full =====", flush=True)

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
        vram_limit = max(1.0, total_gb - settings.hidream_vram_reserve_gb)

        self._pipe = HiDreamO1ImagePipeline.from_pretrained(
            torch_dtype=torch.bfloat16,
            device="cuda",
            model_configs=[
                ModelConfig(path=self._model_files(), **vram_config),
            ],
            processor_config=ModelConfig(path=str(settings.hidream_dir)),
            vram_limit=vram_limit,
        )

        print(
            f"===== HiDream-O1-Image Full 加载完成，显存预算 {vram_limit:.1f} GB =====",
            flush=True,
        )
        return self._pipe

    def generate(self, job_id: str, payload: dict) -> str:
        pipe = self._load()

        width = int(payload["width"])
        height = int(payload["height"])
        steps = int(payload.get("steps") or settings.hidream_steps)
        cfg_scale = float(payload.get("cfg_scale") or settings.hidream_cfg_scale)
        shift = float(payload.get("shift") or settings.hidream_shift)
        noise_scale = float(payload.get("noise_scale") or settings.hidream_noise_scale)
        seed = payload.get("seed")
        edit_images = payload.get("edit_images") or []
        keep_original_aspect = bool(payload.get("keep_original_aspect", False))

        mode = "文生图"
        if len(edit_images) == 1:
            mode = "单图编辑"
        elif len(edit_images) >= 2:
            mode = f"多参考生成({len(edit_images)}张)"

        print(
            f"[HiDream] {job_id} 开始{mode}：{width}x{height}，"
            f"{steps} steps，CFG={cfg_scale:g}，shift={shift:g}，noise={noise_scale:g}",
            flush=True,
        )
        jobs.update(job_id, progress=5)

        image = pipe(
            prompt=payload["prompt"],
            negative_prompt=payload.get("negative_prompt") or " ",
            cfg_scale=cfg_scale,
            height=height,
            width=width,
            seed=seed,
            num_inference_steps=steps,
            model_type="full",
            shift=shift,
            noise_scale=noise_scale,
            edit_image=edit_images or None,
            keep_original_aspect=keep_original_aspect,
        )
        jobs.update(job_id, progress=95)

        output_path = settings.output_dir / "images" / f"{job_id}.png"
        image.save(output_path, format="PNG")

        # H3 与 HiDream 共用一张 GPU。任务完成后主动卸载，给下一个模型留出完整显存。
        if settings.hidream_release_vram_after_job:
            pipe.load_models_to_device([])
            torch.cuda.empty_cache()

        print(f"[HiDream] {job_id} 生成完成：{output_path}", flush=True)
        return str(output_path)


hidream_backend = HiDreamO1ImageBackend()
