import base64
import hmac
import io
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


app = FastAPI(title="mmax-api", version="0.1.0")


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
    return {
        "id": model_id,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "local",
        "type": kind,
        "ready": ready,
        "ready_reason": reason,
    }


def _first_form_value(form, names):
    for name in names:
        value = form.get(name)
        if value is not None and value != "":
            return value
    return None


def _download_image(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise APIError(400, "参考图片必须是上传文件、data:image 或 http/https URL。", param="input_reference")
    req = urllib.request.Request(url, headers={"User-Agent": "mmax-api/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read(settings.max_input_image_bytes + 1)
    except Exception as exc:
        raise APIError(400, f"参考图片下载失败：{exc}", param="input_reference") from exc
    return data


async def _load_image(value, field_name: str):
    if value is None:
        return None
    if hasattr(value, "read") and hasattr(value, "filename"):
        data = await value.read()
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


@app.post("/v1/videos")
async def create_video(request: Request, _=Depends(require_auth)):
    form = await request.form()
    prompt = str(form.get("prompt") or "").strip()
    model = str(form.get("model") or h3_backend.model_id).strip()
    seconds = str(form.get("seconds") or "4").strip()
    size = str(form.get("size") or "1280x720").strip()

    if not prompt:
        raise APIError(400, "prompt 不能为空。", param="prompt")
    if model != h3_backend.model_id:
        raise APIError(404, f"视频模型 '{model}' 不存在。", "model_not_found", "model")
    if seconds not in h3_backend.VALID_SECONDS:
        raise APIError(400, "seconds 目前支持 4、8、12。", param="seconds")
    if size not in h3_backend.VALID_SIZES:
        raise APIError(400, "不支持该视频尺寸。", param="size")

    first_value = _first_form_value(form, ("input_reference", "image", "first_frame", "image_start"))
    last_value = _first_form_value(form, ("image_tail", "last_frame", "end_frame", "image_end"))
    first_image = await _load_image(first_value, "input_reference")
    last_image = await _load_image(last_value, "image_tail")

    keyframes = []
    keyframe_indices = []
    if first_image is not None:
        keyframes.append(first_image)
        keyframe_indices.append(0)
    if last_image is not None:
        keyframes.append(last_image)
        keyframe_indices.append(-1)

    payload = {
        "prompt": prompt,
        "seconds": seconds,
        "size": size,
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


@app.post("/v1/images")
async def create_image(request: Request, _=Depends(require_auth)):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        prompt = str(body.get("prompt") or "").strip()
        model = str(body.get("model") or krea2_backend.model_id).strip()
        size = str(body.get("size") or "1024x1024").strip()
        seed = body.get("seed")
    else:
        form = await request.form()
        prompt = str(form.get("prompt") or "").strip()
        model = str(form.get("model") or krea2_backend.model_id).strip()
        size = str(form.get("size") or "1024x1024").strip()
        seed = form.get("seed")

    if not prompt:
        raise APIError(400, "prompt 不能为空。", param="prompt")
    if model != krea2_backend.model_id:
        raise APIError(404, f"图片模型 '{model}' 不存在。", "model_not_found", "model")
    width, height = _parse_size(size)
    if seed not in (None, ""):
        try:
            seed = int(seed)
        except Exception as exc:
            raise APIError(400, "seed 必须是整数。", param="seed") from exc
    else:
        seed = None

    payload = {"prompt": prompt, "width": width, "height": height, "size": size, "seed": seed}
    job = jobs.create("image", model, payload)
    scheduler.submit(job["id"], lambda job_id: krea2_backend.generate(job_id, payload))
    return _public_job(job)


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
