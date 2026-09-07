import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("MMAX_HOST", "0.0.0.0")
    port: int = int(os.getenv("MMAX_PORT", "6006"))

    api_key: str = os.getenv("MMAX_API_KEY", "")
    api_key_file: Path = _path("MMAX_API_KEY_FILE", "/root/autodl-tmp/mmax/.api_key")

    output_dir: Path = _path("MMAX_OUTPUT_DIR", "/root/autodl-tmp/outputs")
    runtime_dir: Path = _path("MMAX_RUNTIME_DIR", "/root/autodl-tmp/mmax/runtime")

    h3_enabled: bool = _bool("MMAX_H3_ENABLED", True)
    h3_model_id: str = os.getenv("MMAX_H3_MODEL_ID", "minimax-h3")
    h3_dit: Path = _path("MMAX_H3_DIT", "/root/autodl-tmp/models/h3/DiffSynth-Studio/MiniMax-H3-NF4/minimax-h3-fl2va-pruned-nf4.safetensors")
    h3_text_encoder: Path = _path("MMAX_H3_TEXT_ENCODER", "/root/autodl-tmp/models/h3/DiffSynth-Studio/MiniMax-H3-NF4/minimax-h3-text-encoder-nf4.safetensors")
    h3_video_vae: Path = _path("MMAX_H3_VIDEO_VAE", "/root/autodl-tmp/models/h3/DiffSynth-Studio/MiniMax-H3-NF4/video_vae_nf4.safetensors")
    h3_audio_vae: Path = _path("MMAX_H3_AUDIO_VAE", "/root/autodl-tmp/models/h3/DiffSynth-Studio/MiniMax-H3-NF4/audio_vae_nf4.safetensors")
    h3_processor: Path = _path("MMAX_H3_PROCESSOR", "/root/autodl-tmp/models/h3/MiniMaxAI/MiniMax-H3/FL2VA/processor")
    # 官方同款 NF4 Pruned FL2VA 示例使用 50 steps。默认 20 兼顾速度和质量。
    h3_steps: int = int(os.getenv("MMAX_H3_STEPS", "20"))
    h3_vram_reserve_gb: float = float(os.getenv("MMAX_H3_VRAM_RESERVE_GB", "4"))
    h3_crf: int = int(os.getenv("MMAX_H3_CRF", "18"))
    h3_sharpen: float = float(os.getenv("MMAX_H3_SHARPEN", "0.35"))

    hidream_enabled: bool = _bool("MMAX_HIDREAM_ENABLED", True)
    hidream_model_id: str = os.getenv("MMAX_HIDREAM_MODEL_ID", "hidream-o1-image")
    hidream_dir: Path = _path("MMAX_HIDREAM_DIR", "/root/autodl-tmp/models/hidream-o1-image")
    # DiffSynth HiDream-O1-Image Full 推荐参数。
    hidream_steps: int = int(os.getenv("MMAX_HIDREAM_STEPS", "50"))
    hidream_cfg_scale: float = float(os.getenv("MMAX_HIDREAM_CFG_SCALE", "4.0"))
    hidream_shift: float = float(os.getenv("MMAX_HIDREAM_SHIFT", "3.0"))
    # 多参考 subject-driven 官方示例使用 shift=1。
    hidream_subject_shift: float = float(os.getenv("MMAX_HIDREAM_SUBJECT_SHIFT", "1.0"))
    hidream_noise_scale: float = float(os.getenv("MMAX_HIDREAM_NOISE_SCALE", "8.0"))
    # 测试阶段尽量利用显存；如与其他进程共享 GPU，可调大该值。
    hidream_vram_reserve_gb: float = float(os.getenv("MMAX_HIDREAM_VRAM_RESERVE_GB", "0.5"))
    hidream_max_pixels: int = int(os.getenv("MMAX_HIDREAM_MAX_PIXELS", "4194304"))
    hidream_max_reference_images: int = int(os.getenv("MMAX_HIDREAM_MAX_REFERENCE_IMAGES", "10"))
    hidream_release_vram_after_job: bool = _bool("MMAX_HIDREAM_RELEASE_VRAM_AFTER_JOB", True)

    max_input_image_bytes: int = int(os.getenv("MMAX_MAX_INPUT_IMAGE_BYTES", str(20 * 1024 * 1024)))

    def resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key.strip()
        if self.api_key_file.exists():
            return self.api_key_file.read_text(encoding="utf-8").strip()
        return ""

    def ensure_runtime_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "videos").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "images").mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
