import os
import random
import subprocess
from pathlib import Path

import torch

from .base import Backend
from ..config import settings
from ..jobs import jobs


class H3Backend(Backend):
    """MiniMax H3 视频/音频后端，保留当前服务器已验证稳定的推理参数。"""

    kind = "video"

    VALID_SIZES = {"1280x720", "720x1280", "1792x1024", "1024x1792"}
    VALID_SECONDS = {"4", "8", "12"}
    INTERNAL_SIZE = {
        "1280x720": (832, 480),
        "1792x1024": (832, 480),
        "720x1280": (480, 832),
        "1024x1792": (480, 832),
    }

    def __init__(self) -> None:
        self.model_id = settings.h3_model_id
        self._pipe = None

    def _paths(self) -> list[Path]:
        return [
            settings.h3_dit,
            settings.h3_text_encoder,
            settings.h3_video_vae,
            settings.h3_audio_vae,
            settings.h3_processor,
        ]

    def ready(self) -> tuple[bool, str | None]:
        if not settings.h3_enabled:
            return False, "H3 已在配置中关闭"
        missing = [str(path) for path in self._paths() if not path.exists()]
        if missing:
            return False, "缺少模型文件：" + ", ".join(missing)
        return True, None

    @staticmethod
    def align_frames(seconds: int) -> int:
        target = seconds * 24
        if target <= 5:
            return 5
        return 17 * ((target - 5 + 16) // 17) + 5

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        ok, reason = self.ready()
        if not ok:
            raise RuntimeError(reason)

        from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Pipeline, ModelConfig

        print("===== 正在加载 MiniMax H3 =====", flush=True)
        vram_config = {
            "offload_dtype": "disk",
            "offload_device": "disk",
            "onload_dtype": torch.bfloat16,
            "onload_device": "cpu",
            "preparing_dtype": torch.bfloat16,
            "preparing_device": "cuda",
            "computation_dtype": torch.bfloat16,
            "computation_device": "cuda",
        }
        total_gb = torch.cuda.mem_get_info("cuda")[1] / (1024 ** 3)
        self._pipe = MiniMaxH3Pipeline.from_pretrained(
            torch_dtype=torch.bfloat16,
            device="cuda",
            model_configs=[
                ModelConfig(path=str(settings.h3_dit), **vram_config),
                ModelConfig(path=str(settings.h3_text_encoder), **vram_config),
                ModelConfig(path=str(settings.h3_video_vae), **vram_config),
                ModelConfig(path=str(settings.h3_audio_vae), **vram_config),
            ],
            processor_config=ModelConfig(path=str(settings.h3_processor)),
            vram_limit=max(1.0, total_gb - settings.h3_vram_reserve_gb),
        )
        print("===== MiniMax H3 加载完成 =====", flush=True)
        return self._pipe

    def generate(self, job_id: str, payload: dict) -> str:
        from diffsynth.utils.data.audio_video import write_video_audio

        pipe = self._load()
        seconds = int(payload["seconds"])
        requested_size = payload["size"]
        internal_width, internal_height = self.INTERNAL_SIZE[requested_size]
        target_width, target_height = [int(v) for v in requested_size.split("x")]
        frames = self.align_frames(seconds)
        seed = payload.get("seed")
        if seed is None:
            seed = random.randint(0, 2**31 - 1)

        video_dir = settings.output_dir / "videos"
        raw_path = video_dir / f"{job_id}.raw.mp4"
        final_path = video_dir / f"{job_id}.mp4"

        keyframes = payload.get("keyframes") or None
        keyframe_indices = payload.get("keyframe_indices") or None

        print(
            f"[H3] {job_id} 开始生成：{internal_width}x{internal_height}, "
            f"{seconds}s, {frames} 帧, {settings.h3_steps} steps",
            flush=True,
        )
        jobs.update(job_id, progress=5)

        video, audio = pipe(
            prompt=payload["prompt"],
            height=internal_height,
            width=internal_width,
            num_frames=frames,
            num_inference_steps=settings.h3_steps,
            seed=seed,
            keyframes=keyframes,
            keyframe_indices=keyframe_indices,
        )
        jobs.update(job_id, progress=85)

        write_video_audio(
            video=video,
            audio=audio,
            output_path=str(raw_path),
            fps=24,
            audio_sample_rate=32000,
        )
        jobs.update(job_id, progress=92)

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(raw_path),
            "-vf", f"scale={target_width}:{target_height}:flags=lanczos",
            "-t", str(seconds),
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(final_path),
        ]
        subprocess.run(cmd, check=True)
        if raw_path.exists():
            os.remove(raw_path)

        print(f"[H3] {job_id} 生成完成：{final_path}", flush=True)
        return str(final_path)


h3_backend = H3Backend()
