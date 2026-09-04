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
    h3_dit: Path = _path("MMAX_H3_DIT", "/root/autodl-tmp/h3/models/DiffSynth-Studio/MiniMax-H3-NF4/minimax-h3-fl2va-pruned-nf4.safetensors")
    h3_text_encoder: Path = _path("MMAX_H3_TEXT_ENCODER", "/root/autodl-tmp/h3/models/DiffSynth-Studio/MiniMax-H3-NF4/minimax-h3-text-encoder-nf4.safetensors")
    h3_video_vae: Path = _path("MMAX_H3_VIDEO_VAE", "/root/autodl-tmp/h3/models/DiffSynth-Studio/MiniMax-H3-NF4/video_vae_nf4.safetensors")
    h3_audio_vae: Path = _path("MMAX_H3_AUDIO_VAE", "/root/autodl-tmp/h3/models/DiffSynth-Studio/MiniMax-H3-NF4/audio_vae_nf4.safetensors")
    h3_processor: Path = _path("MMAX_H3_PROCESSOR", "/root/autodl-tmp/h3/models/MiniMaxAI/MiniMax-H3/FL2VA/processor")
    h3_steps: int = int(os.getenv("MMAX_H3_STEPS", "10"))
    h3_vram_reserve_gb: float = float(os.getenv("MMAX_H3_VRAM_RESERVE_GB", "4"))

    krea_enabled: bool = _bool("MMAX_KREA_ENABLED", True)
    krea_model_id: str = os.getenv("MMAX_KREA_MODEL_ID", "krea-2-turbo")
    krea_dit: Path = _path("MMAX_KREA_DIT", "/root/autodl-tmp/models/krea2/krea2_turbo_bf16.safetensors")
    krea_text_encoder: Path = _path("MMAX_KREA_TEXT_ENCODER", "/root/autodl-tmp/models/krea2/qwen3vl_4b_bf16.safetensors")
    krea_vae: Path = _path("MMAX_KREA_VAE", "/root/autodl-tmp/models/krea2/qwen_image/vae/diffusion_pytorch_model.safetensors")
    krea_tokenizer: Path = _path("MMAX_KREA_TOKENIZER", "/root/autodl-tmp/models/krea2/qwen3vl_tokenizer")
    krea_vram_reserve_gb: float = float(os.getenv("MMAX_KREA_VRAM_RESERVE_GB", "2"))
    krea_max_pixels: int = int(os.getenv("MMAX_KREA_MAX_PIXELS", "4194304"))

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
