import asyncio
import base64
import hmac
import io
import json
import math
import time
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image

from .backends.h3 import h3_backend
from .backends.hidream import hidream_backend
from .config import settings
from .jobs import jobs
from .scheduler import scheduler

settings.ensure_runtime_dirs()


class APIError(Exception):
    """统一 API 错误。"""

    def __init__(self, status_code: int, message: str, code: str | None = None, param: str | None = None):
        self.status_code = status_code
        self.message = message
        self.code = code
        self.param = param


app = FastAPI(title="mmax-api", version="0.4.0")


@app.exception_handler(APIError)
async def api_error_handler(_request: Request, exc: APIError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.message,
                "type": "invalid_request_error" if exc.status_code != 401 else "authentication_error",
                "param": exc.param,
                "code": exc.code,
            }
        },
    )


def require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    api_key = settings.resolved_api_key()
    if not api_key:
        raise APIError(500, "服务端尚未配置 API Key。", "server_configuration_error")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise APIError(401, "缺少 Bearer 鉴权。", "invalid_api_key")
    token = authorization[7:].strip()
    if not hmac.compare_digest(token, api_key):
        raise APIError(401, "API Key 不正确。", "invalid_api_key")


def _public_job(job: dict) -> dict:
    data = {k: v for k, v in job.items() if k not in {"payload", "output_path"}}
    if job["status"] == "completed":
        plural = "videos" if job["object"] == "video" else "images"
        data["content_url"] = f"/v1/{plural}/{job['id']}/content"
        if job["object"] == "video":
            data["video_url"] = data["content_url"]
    return data


def _model_object(model_id: str, kind: str, ready: bool, reason: str | None) -> dict:
    if kind == "image":
        capabilities = {
            "text_to_image": True,
            "image_to_image": True,
            "instruction_edit": True,
            "multi_reference_subject": True,
            "max_reference_images": settings.hidream_max_reference_images,
            "keep_original_aspect": True,
            "mask_edit": False,
            "response_formats": ["url", "b64_json"],
            "default_steps": settings.hidream_steps,
            "default_cfg_scale": settings.hidream_cfg_scale,
            "default_shift": settings.hidream_shift,
            "default_noise_scale": settings.hidream_noise_scale,
        }
        endpoints = {
            "generate": "/v1/images/generations",
            "edit": "/v1/images/edits",
        }
    else:
        capabilities = {
            "text_to_video": True,
            "image_to_video": True,
            "first_frame": True,
            "last_frame": True,
            "arbitrary_keyframes": True,
            "native_audio": True,
            "reference_to_video": False,
            "min_seconds": h3_backend.MIN_SECONDS,
            "max_seconds": h3_backend.MAX_SECONDS,
        }
        endpoints = {
            "create": "/v1/videos",
            "retrieve": "/v1/videos/{video_id}",
            "content": "/v1/videos/{video_id}/content",
        }

    return {
        "id": model_id,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "local",
        "type": kind,
        "ready": ready,
        "ready_reason": reason,
        "capabilities": capabilities,
        "endpoints": endpoints,
    }


def _download_image(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise APIError(400, "图片必须是上传文件、data:image 或 http/https URL。", param="image")
    req = urllib.request.Request(url, headers={"User-Agent": "mmax-api/0.4"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read(settings.max_input_image_bytes + 1)
    except Exception as exc:
        raise APIError(400, f"图片下载失败：{exc}", param="image") from exc
    return data


async def _load_image(value, field_name: str):
    if value is None:
        return None
    if hasattr(value, "read") and hasattr(value, "filename"):
        data = await value.read()
    elif isinstance(value, dict):
        url = value.get("url") or value.get("image_url")
        if not isinstance(url, str):
            raise APIError(400, f"{field_name} 图片对象必须包含 url。", param=field_name)
        return await _load_image(url, field_name)
    elif isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if value.startswith("data:image/"):
            try:
                _, encoded = value.split(",", 1)
                data = base64.b64decode(encoded)
            except Exception as exc:
                raise APIError(400, f"{field_name} 的 data URL 无效。", param=field_name) from exc
        else:
            data = _download_image(value)
    else:
        raise APIError(400, f"{field_name} 的图片参数无效。", param=field_name)

    if not data or len(data) > settings.max_input_image_bytes:
        raise APIError(400, f"{field_name} 为空或超过大小限制。", param=field_name)
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image.convert("RGB")
    except Exception as exc:
        raise APIError(400, f"{field_name} 不是有效图片：{exc}", param=field_name) from exc


def _collect_image_values(body) -> list:
    if hasattr(body, "getlist"):
        values = body.getlist("image")
        if not values:
            values = body.getlist("images")
    else:
        raw = body.get("image")
        if raw is None:
            raw = body.get("images")
        values = raw if isinstance(raw, list) else [raw]
    return [value for value in values if value not in (None, "")]


def _parse_size(size: str) -> tuple[int, int]:
    try:
        width, height = [int(v) for v in size.lower().split("x", 1)]
    except Exception as exc:
        raise APIError(400, "size 格式必须类似 1024x1024。", param="size") from exc
    if width <= 0 or height <= 0 or width % 16 or height % 16:
        raise APIError(400, "图片宽高必须为正数并且能被 16 整除。", param="size")
    pixels = width * height
    if pixels > settings.hidream_max_pixels:
        raise APIError(
            400,
            f"请求尺寸 {width}x{height}，共 {pixels:,} 像素；服务器上限 {settings.hidream_max_pixels:,} 像素。",
            param="size",
        )
    return width, height


def _parse_seed(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception as exc:
        raise APIError(400, "seed 必须是整数。", param="seed") from exc


def _parse_n(value) -> int:
    if value in (None, ""):
        return 1
    try:
        n = int(value)
    except Exception as exc:
        raise APIError(400, "n 必须是整数。", param="n") from exc
    if n < 1 or n > 4:
        raise APIError(400, "n 目前支持 1 到 4。", param="n")
    return n


def _parse_steps(value, default: int, *, max_steps: int = 80) -> int:
    if value in (None, ""):
        return default
    try:
        steps = int(value)
    except Exception as exc:
        raise APIError(400, "steps 必须是整数。", param="steps") from exc
    if not 1 <= steps <= max_steps:
        raise APIError(400, f"steps 必须在 1 到 {max_steps} 之间。", param="steps")
    return steps


def _parse_float(value, default: float, param: str, minimum: float, maximum: float) -> float:
    if value in (None, ""):
        return default
    try:
        result = float(value)
    except Exception as exc:
        raise APIError(400, f"{param} 必须是数字。", param=param) from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise APIError(400, f"{param} 必须在 {minimum:g} 到 {maximum:g} 之间。", param=param)
    return result


def _parse_bool(value, default: bool, param: str) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise APIError(400, f"{param} 必须是布尔值。", param=param)


def _parse_seconds(value) -> float:
    try:
        seconds = float(value)
    except Exception as exc:
        raise APIError(400, "seconds 必须是数字。", param="seconds") from exc
    if not math.isfinite(seconds) or not h3_backend.MIN_SECONDS <= seconds <= h3_backend.MAX_SECONDS:
        raise APIError(
            400,
            f"seconds 必须在 {h3_backend.MIN_SECONDS:g} 到 {h3_backend.MAX_SECONDS:g} 秒之间。",
            param="seconds",
        )
    return seconds


def _parse_response_format(value) -> str:
    response_format = str(value or "url").strip().lower()
    if response_format not in {"url", "b64_json"}:
        raise APIError(400, "response_format 仅支持 url 或 b64_json。", param="response_format")
    return response_format


async def _wait_for_job(job_id: str) -> dict:
    while True:
        job = jobs.get(job_id)
        if not job:
            raise APIError(500, "内部任务丢失。", "job_lost")
        if job["status"] == "completed":
            return job
        if job["status"] == "failed":
            error = job.get("error") or {}
            raise APIError(500, error.get("message", "生成失败。"), error.get("code", "generation_failed"))
        await asyncio.sleep(0.25)


def _openai_image_item(job: dict, prompt: str, response_format: str) -> dict:
    path = Path(job["output_path"])
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    item = {"revised_prompt": prompt}
    if response_format == "b64_json":
        item["b64_json"] = encoded
    else:
        item["url"] = f"data:image/png;base64,{encoded}"
    return item


async def _run_image_jobs(
    *,
    prompt: str,
    negative_prompt: str,
    model: str,
    width: int,
    height: int,
    seed: int | None,
    n: int,
    steps: int,
    cfg_scale: float,
    shift: float,
    noise_scale: float,
    response_format: str,
    edit_images: list[Image.Image] | None = None,
    keep_original_aspect: bool = False,
) -> dict:
    submitted = []
    for index in range(n):
        current_seed = None if seed is None else seed + index
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "size": f"{width}x{height}",
            "seed": current_seed,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "shift": shift,
            "noise_scale": noise_scale,
            "edit_images": edit_images or [],
            "keep_original_aspect": keep_original_aspect,
        }
        job = jobs.create("image", model, payload)
        scheduler.submit(job["id"], lambda job_id, p=payload: hidream_backend.generate(job_id, p))
        submitted.append(job["id"])

    completed = [await _wait_for_job(job_id) for job_id in submitted]
    return {
        "created": int(time.time()),
        "data": [_openai_image_item(job, prompt, response_format) for job in completed],
    }


@app.get("/health")
def health():
    h3_ok, h3_reason = h3_backend.ready()
    hidream_ok, hidream_reason = hidream_backend.ready()
    return {
        "status": "ok",
        "queue_pending": scheduler.pending,
        "models": {
            h3_backend.model_id: {"ready": h3_ok, "reason": h3_reason},
            hidream_backend.model_id: {"ready": hidream_ok, "reason": hidream_reason},
        },
    }


@app.get("/v1/models")
def list_models(_=Depends(require_auth)):
    h3_ok, h3_reason = h3_backend.ready()
    hidream_ok, hidream_reason = hidream_backend.ready()
    return {
        "object": "list",
        "data": [
            _model_object(h3_backend.model_id, "video", h3_ok, h3_reason),
            _model_object(hidream_backend.model_id, "image", hidream_ok, hidream_reason),
        ],
    }


@app.get("/v1/models/{model_id}")
def retrieve_model(model_id: str, _=Depends(require_auth)):
    for backend in (h3_backend, hidream_backend):
        if backend.model_id == model_id:
            ok, reason = backend.ready()
            return _model_object(backend.model_id, backend.kind, ok, reason)
    raise APIError(404, f"模型 '{model_id}' 不存在。", "model_not_found", "model")


@app.post("/v1/images/generations")
async def create_image_generation(request: Request, _=Depends(require_auth)):
    content_type = request.headers.get("content-type", "")
    body = await request.json() if "application/json" in content_type else await request.form()

    prompt = str(body.get("prompt") or "").strip()
    negative_prompt = str(body.get("negative_prompt") or " ").strip() or " "
    model = str(body.get("model") or hidream_backend.model_id).strip()
    size = str(body.get("size") or "1024x1024").strip()
    seed = _parse_seed(body.get("seed"))
    n = _parse_n(body.get("n"))
    steps = _parse_steps(body.get("steps") or body.get("num_inference_steps"), settings.hidream_steps)
    cfg_scale = _parse_float(
        body.get("cfg_scale") or body.get("guidance_scale"),
        settings.hidream_cfg_scale,
        "cfg_scale",
        0.0,
        20.0,
    )
    shift = _parse_float(body.get("shift"), settings.hidream_shift, "shift", 0.1, 20.0)
    noise_scale = _parse_float(body.get("noise_scale"), settings.hidream_noise_scale, "noise_scale", 0.0, 32.0)
    response_format = _parse_response_format(body.get("response_format"))

    if not prompt:
        raise APIError(400, "prompt 不能为空。", param="prompt")
    if model != hidream_backend.model_id:
        raise APIError(404, f"图片模型 '{model}' 不存在。", "model_not_found", "model")
    width, height = _parse_size(size)

    return await _run_image_jobs(
        prompt=prompt,
        negative_prompt=negative_prompt,
        model=model,
        width=width,
        height=height,
        seed=seed,
        n=n,
        steps=steps,
        cfg_scale=cfg_scale,
        shift=shift,
        noise_scale=noise_scale,
        response_format=response_format,
    )


@app.post("/v1/images/edits")
async def create_image_edit(request: Request, _=Depends(require_auth)):
    content_type = request.headers.get("content-type", "")
    body = await request.json() if "application/json" in content_type else await request.form()

    prompt = str(body.get("prompt") or "").strip()
    negative_prompt = str(body.get("negative_prompt") or " ").strip() or " "
    model = str(body.get("model") or hidream_backend.model_id).strip()
    size = str(body.get("size") or "1024x1024").strip()
    seed = _parse_seed(body.get("seed"))
    n = _parse_n(body.get("n"))
    steps = _parse_steps(body.get("steps") or body.get("num_inference_steps"), settings.hidream_steps)
    cfg_scale = _parse_float(
        body.get("cfg_scale") or body.get("guidance_scale"),
        settings.hidream_cfg_scale,
        "cfg_scale",
        0.0,
        20.0,
    )
    response_format = _parse_response_format(body.get("response_format"))

    if not prompt:
        raise APIError(400, "prompt 不能为空。", param="prompt")
    if model != hidream_backend.model_id:
        raise APIError(404, f"图片模型 '{model}' 不存在。", "model_not_found", "model")
    if body.get("mask") not in (None, ""):
        raise APIError(400, "HiDream 当前接口不支持 mask 局部编辑。", "unsupported_capability", "mask")

    image_values = _collect_image_values(body)
    if not image_values:
        raise APIError(400, "至少需要提供 1 张参考图。", param="image")
    if len(image_values) > settings.hidream_max_reference_images:
        raise APIError(
            400,
            f"参考图最多支持 {settings.hidream_max_reference_images} 张。",
            "unsupported_capability",
            "image",
        )

    edit_images = [
        await _load_image(value, f"image[{index}]")
        for index, value in enumerate(image_values)
    ]

    keep_original_aspect = _parse_bool(
        body.get("keep_original_aspect"),
        len(edit_images) == 1,
        "keep_original_aspect",
    )
    if keep_original_aspect and len(edit_images) != 1:
        raise APIError(
            400,
            "keep_original_aspect 仅适用于恰好 1 张参考图。",
            "unsupported_capability",
            "keep_original_aspect",
        )

    default_shift = settings.hidream_subject_shift if len(edit_images) >= 2 else settings.hidream_shift
    shift = _parse_float(body.get("shift"), default_shift, "shift", 0.1, 20.0)
    noise_scale = _parse_float(body.get("noise_scale"), settings.hidream_noise_scale, "noise_scale", 0.0, 32.0)
    width, height = _parse_size(size)

    return await _run_image_jobs(
        prompt=prompt,
        negative_prompt=negative_prompt,
        model=model,
        width=width,
        height=height,
        seed=seed,
        n=n,
        steps=steps,
        cfg_scale=cfg_scale,
        shift=shift,
        noise_scale=noise_scale,
        response_format=response_format,
        edit_images=edit_images,
        keep_original_aspect=keep_original_aspect,
    )


@app.get("/v1/images/{job_id}")
def get_image(job_id: str, _=Depends(require_auth)):
    job = jobs.get(job_id)
    if not job or job["object"] != "image":
        raise APIError(404, "图片任务不存在。", "not_found")
    return _public_job(job)


@app.get("/v1/images/{job_id}/content")
def get_image_content(job_id: str, _=Depends(require_auth)):
    job = jobs.get(job_id)
    if not job or job["object"] != "image":
        raise APIError(404, "图片任务不存在。", "not_found")
    if job["status"] != "completed" or not job.get("output_path"):
        raise APIError(409, "图片尚未生成完成。", "not_ready")
    return FileResponse(job["output_path"], media_type="image/png", filename=f"{job_id}.png")


async def _parse_keyframe_list(raw, existing_indices: set[int], frame_count: int):
    if raw in (None, ""):
        return [], []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception as exc:
            raise APIError(400, "keyframes 必须是 JSON 数组。", param="keyframes") from exc
    if not isinstance(raw, list):
        raise APIError(400, "keyframes 必须是数组。", param="keyframes")

    images = []
    indices = []
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            raise APIError(400, f"keyframes[{position}] 必须是对象。", param="keyframes")
        if "image" not in item or "index" not in item:
            raise APIError(400, f"keyframes[{position}] 必须包含 image 和 index。", param="keyframes")
        try:
            index = int(item["index"])
        except Exception as exc:
            raise APIError(400, f"keyframes[{position}].index 必须是整数。", param="keyframes") from exc
        if index != -1 and not 0 <= index < frame_count:
            raise APIError(400, f"keyframes[{position}].index 超出当前视频帧范围。", param="keyframes")
        normalized_index = frame_count - 1 if index == -1 else index
        if normalized_index in existing_indices:
            raise APIError(400, f"关键帧索引 {index} 重复。", param="keyframes")
        image = await _load_image(item["image"], f"keyframes[{position}].image")
        images.append(image)
        indices.append(index)
        existing_indices.add(normalized_index)
    return images, indices


@app.post("/v1/videos")
async def create_video(request: Request, _=Depends(require_auth)):
    content_type = request.headers.get("content-type", "")
    is_json = "application/json" in content_type
    body = await request.json() if is_json else await request.form()

    prompt = str(body.get("prompt") or "").strip()
    model = str(body.get("model") or h3_backend.model_id).strip()
    seconds = _parse_seconds(body.get("seconds") or body.get("duration") or 4)
    size = str(body.get("size") or "1280x720").strip()
    seed = _parse_seed(body.get("seed"))
    steps = _parse_steps(body.get("steps") or body.get("num_inference_steps"), settings.h3_steps)

    if not prompt:
        raise APIError(400, "prompt 不能为空。", param="prompt")
    if model != h3_backend.model_id:
        raise APIError(404, f"视频模型 '{model}' 不存在。", "model_not_found", "model")
    if size not in h3_backend.VALID_SIZES:
        raise APIError(400, "不支持该视频尺寸。", param="size")

    frame_count = h3_backend.align_frames(seconds)
    keyframes = []
    keyframe_indices = []
    used_indices: set[int] = set()

    first_value = body.get("input_reference")
    if first_value not in (None, ""):
        first_image = await _load_image(first_value, "input_reference")
        keyframes.append(first_image)
        keyframe_indices.append(0)
        used_indices.add(0)

    end_value = body.get("end_reference")
    if end_value not in (None, ""):
        end_image = await _load_image(end_value, "end_reference")
        keyframes.append(end_image)
        keyframe_indices.append(-1)
        used_indices.add(frame_count - 1)

    extra_images, extra_indices = await _parse_keyframe_list(
        body.get("keyframes"), used_indices, frame_count
    )
    keyframes.extend(extra_images)
    keyframe_indices.extend(extra_indices)

    payload = {
        "prompt": prompt,
        "seconds": seconds,
        "size": size,
        "seed": seed,
        "steps": steps,
        "keyframes": keyframes,
        "keyframe_indices": keyframe_indices,
    }
    job = jobs.create("video", model, payload)
    scheduler.submit(job["id"], lambda job_id: h3_backend.generate(job_id, payload))
    return _public_job(job)


@app.get("/v1/videos/{job_id}")
def get_video(job_id: str, _=Depends(require_auth)):
    job = jobs.get(job_id)
    if not job or job["object"] != "video":
        raise APIError(404, "视频任务不存在。", "not_found")
    return _public_job(job)


@app.get("/v1/videos/{job_id}/content")
def get_video_content(job_id: str, _=Depends(require_auth)):
    job = jobs.get(job_id)
    if not job or job["object"] != "video":
        raise APIError(404, "视频任务不存在。", "not_found")
    if job["status"] != "completed" or not job.get("output_path"):
        raise APIError(409, "视频尚未生成完成。", "not_ready")
    return FileResponse(job["output_path"], media_type="video/mp4", filename=f"{job_id}.mp4")
