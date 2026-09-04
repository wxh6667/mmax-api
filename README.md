# mmax-api

A single local FastAPI service for:

- **MiniMax H3** video + audio generation
- **Krea 2 Turbo** image generation

Both models share one public API port and one FIFO GPU worker. This prevents two heavyweight generation jobs from fighting for the same GPU.

> This repository contains service code only. Model weights are not redistributed. You are responsible for downloading model files and complying with each model's license.

## API

Default port: `6006`.

```text
GET  /health

GET  /v1/models
GET  /v1/models/{model_id}

POST /v1/videos
GET  /v1/videos/{video_id}
GET  /v1/videos/{video_id}/content

POST /v1/images
GET  /v1/images/{image_id}
GET  /v1/images/{image_id}/content
```

All `/v1/*` routes require:

```text
Authorization: Bearer <your-key>
```

`/health` is intentionally unauthenticated for local process monitoring.

## Architecture

The HTTP server accepts requests immediately and stores them as `queued`. A single background worker consumes jobs in FIFO order:

```text
HTTP -> queue -> one GPU worker -> H3 or Krea -> output
```

The process can keep both pipelines initialized with host-memory offload, while only one generation executes on the GPU at a time.

## Install

```bash
cd /root/autodl-tmp
git clone https://github.com/wxh6667/mmax-api.git mmax
cd mmax
cp .env.example .env
bash ./scripts/install.sh
```

On the original AutoDL layout, the scripts auto-detect:

```text
/root/autodl-tmp/h3/venv/bin/python
/root/autodl-tmp/h3/DiffSynth-Studio
```

## Prepare Krea 2 from existing ComfyUI FP8 files

A common ComfyUI setup has:

```text
/root/autodl-tmp/imagegen/ComfyUI/models/diffusion_models/krea2_turbo_fp8_scaled.safetensors
/root/autodl-tmp/imagegen/ComfyUI/models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors
```

`prepare_krea.py` converts those checkpoints to ordinary local BF16 safetensors and downloads only the tokenizer/config files plus the official Qwen Image VAE:

```bash
PYTHON=/root/autodl-tmp/h3/venv/bin/python
$PYTHON scripts/prepare_krea.py
```

By default the prepared files are placed under:

```text
/root/autodl-tmp/models/krea2/
```

The converter supports the ComfyUI `float8_e4m3fn` format in both legacy `_quantization_metadata` and current per-layer `.comfy_quant` forms.

After the new API has successfully generated both an image and a video, the old ComfyUI application can be removed if it is no longer needed.

## Start and update

```bash
./scripts/start.sh
./scripts/healthcheck.sh
```

Logs:

```bash
tail -f runtime/api.log
```

Stop/restart:

```bash
./scripts/stop.sh
./scripts/restart.sh
```

Update from GitHub:

```bash
./scripts/update.sh
```

`update.sh` performs a fast-forward-only pull, compiles the Python source, restarts the API, and checks `/health`.

## Video request

```bash
curl -X POST http://127.0.0.1:6006/v1/videos \
  -H "Authorization: Bearer $KEY" \
  -F 'model=minimax-h3' \
  -F 'prompt=A cinematic street scene at night' \
  -F 'seconds=4' \
  -F 'size=1280x720'
```

Poll the returned ID with `GET /v1/videos/{id}` and download with `GET /v1/videos/{id}/content` after completion.

### First/last frame

The H3 route supports:

```text
input_reference   first frame
image_tail        last frame
```

Aliases `image`, `first_frame`, `image_start`, `last_frame`, `end_frame`, and `image_end` are also accepted. H3 uses keyframe indices `[0, -1]`, matching the DiffSynth examples.

## Image request

Multipart:

```bash
curl -X POST http://127.0.0.1:6006/v1/images \
  -H "Authorization: Bearer $KEY" \
  -F 'model=krea-2-turbo' \
  -F 'prompt=A black sports car on a rainy Tokyo street, cinematic photography' \
  -F 'size=1024x1024'
```

JSON is also accepted.

Krea 2 Turbo always uses:

```text
num_inference_steps = 8
cfg_scale = 1
mu = 1.15
```

Poll with `GET /v1/images/{id}` and download with `GET /v1/images/{id}/content`.

## Notes

- Jobs are stored in memory. Restarting the API clears job status history, but generated files remain in `outputs/`.
- The server must run with `--workers 1`; multiple workers would create multiple independent GPU queues.
- H3 keeps the proven 10-step default used by this deployment. Change `MMAX_H3_STEPS` if needed.
- Krea image dimensions must be divisible by 16. The default pixel cap is `2048 × 2048`.
- The Qwen Image VAE is deliberately downloaded from the official model instead of reusing an ambiguously detected ComfyUI VAE file.

## Upstream projects

- DiffSynth-Studio: https://github.com/modelscope/DiffSynth-Studio
- ComfyUI quantization format: https://github.com/Comfy-Org/ComfyUI

Model weights remain governed by their respective upstream licenses.

## License

MIT for the service code in this repository.
