import asyncio
import base64
import hmac
import io
import json
import time
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image

from .backends.h3 import h3_backend
from .backends.krea2 import krea2_backend
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


app = FastAPI(title="mmax-api", version="0.2.0")


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
            "max_reference_images": 1,
            "mask_edit": False,
            "response_formats": ["url", "b64_json"],
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


def _first_form_value(form, names):
    for name in names:
        value = form.get(name)
        if value is not None and value != "":
            return value
    return None


def _download_image(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise APIError(400, "图片必须是上传文件、data:image 或 http/https URL。", param="image")
    req = urllib.request.Request(url, headers={"User-Agent": "mmax-api/0.2"})
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


def _parse_size(size: str) -> tuple[int, int]:
    try:
        width, height = [int(v) for v in size.lower().split("x", 1)]
    except Exception as exc:
        raise APIError(400, "size 格式必须类似 1024x1024。", param="size") from exc
    if width <= 0 or height <= 0 or width % 16 or height % 16:
        raise APIError(400, "图片宽高必须为正数并且能被 16 整除。", param="size")
    if width * height > settings.krea_max_pixels:
        raise APIError(400, "图片像素数量超过服务器限制。", param="size")
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
        # 使用自包含 data URL，经过任意网关代理后仍可直接访问，不依赖上游内部地址或 API Key。
        item["url"] = f"data:image/png;base64,{encoded}"
    return item


async def _run_image_jobs(*, prompt: str, model: str, width: int, height: int,
                          seed: int | None, n: int, response_format: str,
                          input_image: Image.Image | None = None, strength: float = 1.0) -> dict:
    submitted = []
    for index in range(n):
        current_seed = None if seed is None else seed + index
        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "size": f"{width}x{height}",
            "seed": current_seed,
            "input_image": input_image,
            "strength": strength,
        }
        job = jobs.create("image", model, payload)
        scheduler.submit(job["id"], lambda job_id, p=payload: krea2_backend.generate(job_id, p))
        submitted.append(job["id"])

    completed = [await _wait_for_job(job_id) for job_id in submitted]
    return {
        "created": int(time.time()),
        "data": [_openai_image_item(job, prompt, response_format) for job in completed],
    }


@app.get("/health")
def health():
    h3_ok, h3_reason = h3_backend.ready()
    krea_ok, krea_reason = krea2_backend.ready()
    return {
        "status": "ok",
        "queue_pending": scheduler.pending,
        "models": {
            h3_backend.model_id: {"ready": h3_ok, "reason": h3_reason},
            krea2_backend.model_id: {"ready": krea_ok, "reason": krea_reason},
        },
    }


@app.get("/v1/models")
def list_models(_=Depends(require_auth)):
    h3_ok, h3_reason = h3_backend.ready()
    krea_ok, krea_reason = krea2_backend.ready()
    return {
        "object": "list",
        "data": [
            _model_object(h3_backend.model_id, "video", h3_ok, h3_reason),
            _model_object(krea2_backend.model_id, "image", krea_ok, krea_reason),
        ],
    }


@app.get("/v1/models/{model_id}")
def retrieve_model(model_id: str, _=Depends(require_auth)):
    for backend in (h3_backend, krea2_backend):
        if backend.model_id == model_id:
            ok, reason = backend.ready()
            return _model_object(backend.model_id, backend.kind, ok, reason)
    raise APIError(404, f"模型 '{model_id}' 不存在。", "model_not_found", "model")


@app.post("/v1/images/generations")
async def create_image_generation(request: Request, _=Depends(require_auth)):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
    else:
        body = await request.form()

    prompt = str(body.get("prompt") or "").strip()
    model = str(body.get("model") or krea2_backend.model_id).strip()
    size = str(body.get("size") or "1024x1024").strip()
    seed = _parse_seed(body.get("seed"))
    n = _parse_n(body.get("n"))
    response_format = _parse_response_format(body.get("response_format"))

    if not prompt:
        raise APIError(400, "prompt 不能为空。", param="prompt")
    if model != krea2_backend.model_id:
        raise APIError(404, f"图片模型 '{model}' 不存在。", "model_not_found", "model")
    width, height = _parse_size(size)

    return await _run_image_jobs(
        prompt=prompt,
        model=model,
        width=width,
        height=height,
        seed=seed,
        n=n,
        response_format=response_format,
    )


@app.post("/v1/images/edits")
async def create_image_edit(request: Request, _=Depends(require_auth)):
    form = await request.form()
    prompt = str(form.get("prompt") or "").strip()
    model = str(form.get("model") or krea2_backend.model_id).strip()
    size = str(form.get("size") or "1024x1024").strip()
    seed = _parse_seed(form.get("seed"))
    n = _parse_n(form.get("n"))
    response_format = _parse_response_format(form.get("response_format"))

    if not prompt:
        raise APIError(400, "prompt 不能为空。", param="prompt")
    if model != krea2_backend.model_id:
        raise APIError(404, f"图片模型 '{model}' 不存在。", "model_not_found", "model")
    if form.get("mask") not in (None, ""):
        raise APIError(400, "当前 Krea 2 后端不支持 mask 局部编辑。", "unsupported_capability", "mask")

    images = form.getlist("image") if hasattr(form, "getlist") else [form.get("image")]
    images = [value for value in images if value not in (None, "")]
    if len(images) != 1:
        raise APIError(400, "当前 Krea 2 后端必须且只能提供 1 张参考图。", "unsupported_capability", "image")
    input_image = await _load_image(images[0], "image")

    try:
        strength = float(form.get("strength") or 0.65)
    except Exception as exc:
        raise APIError(400, "strength 必须是 0 到 1 之间的数字。", param="strength") from exc
    if not 0.0 < strength <= 1.0:
        raise APIError(400, "strength 必须大于 0 且不超过 1。", param="strength")

    width, height = _parse_size(size)
    return await _run_image_jobs(
        prompt=prompt,
        model=model,
        width=width,
        height=height,
        seed=seed,
        n=n,
        response_format=response_format,
        input_image=input_image,
        strength=strength,
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
    seconds = str(body.get("seconds") or body.get("duration") or "4").strip()
    size = str(body.get("size") or "1280x720").strip()
    seed = _parse_seed(body.get("seed"))

    if not prompt:
        raise APIError(400, "prompt 不能为空。", param="prompt")
    if model != h3_backend.model_id:
        raise APIError(404, f"视频模型 '{model}' 不存在。", "model_not_found", "model")
    if seconds not in h3_backend.VALID_SECONDS:
        raise APIError(400, "seconds 目前支持 4、8、12。", param="seconds")
    if size not in h3_backend.VALID_SIZES:
        raise APIError(400, "不支持该视频尺寸。", param="size")

    seconds_int = int(seconds)
    frame_count = h3_backend.align_frames(seconds_int)
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
