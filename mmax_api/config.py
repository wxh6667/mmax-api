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

    qwen_image_enabled: bool = _bool("MMAX_QWEN_IMAGE_ENABLED", True)
    qwen_image_model_id: str = os.getenv("MMAX_QWEN_IMAGE_MODEL_ID", "qwen-image-2512")
    qwen_image_dir: Path = _path("MMAX_QWEN_IMAGE_DIR", "/root/autodl-tmp/models/qwen-image-2512")
    # 官方 Qwen-Image-2512 低显存示例使用 40 steps。
    qwen_image_steps: int = int(os.getenv("MMAX_QWEN_IMAGE_STEPS", "40"))
    qwen_image_cfg_scale: float = float(os.getenv("MMAX_QWEN_IMAGE_CFG_SCALE", "4.0"))
    qwen_image_vram_reserve_gb: float = float(os.getenv("MMAX_QWEN_IMAGE_VRAM_RESERVE_GB", "2"))
    qwen_image_max_pixels: int = int(os.getenv("MMAX_QWEN_IMAGE_MAX_PIXELS", "4194304"))
    # VAE 分块可以显著降低编码/解码阶段的显存峰值。
    qwen_image_vae_tiled: bool = _bool("MMAX_QWEN_IMAGE_VAE_TILED", True)
    qwen_image_tile_size: int = int(os.getenv("MMAX_QWEN_IMAGE_TILE_SIZE", "128"))
    qwen_image_tile_stride: int = int(os.getenv("MMAX_QWEN_IMAGE_TILE_STRIDE", "64"))

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
