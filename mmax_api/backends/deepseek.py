import json
import urllib.request

from ..config import settings


class DeepSeekBackend:
    """DeepSeek-V4.1-Flash 的 OpenAI 兼容代理后端。

    模型由 Xolotl/Strata 在独立进程里常驻，本服务只转发 /v1/chat/completions，
    不加载权重，也不进入图片/视频的 FIFO 队列。文本模型常驻显存，启用前应先
    停掉 H3/HiDream 的生成任务，避免两边抢显存。
    """

    kind = "text"

    def __init__(self) -> None:
        self.model_id = settings.deepseek_model_id

    def _url(self, path: str) -> str:
        return settings.deepseek_base_url.rstrip("/") + path

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.deepseek_api_key:
            headers["Authorization"] = f"Bearer {settings.deepseek_api_key}"
        return headers

    def ready(self) -> tuple[bool, str | None]:
        if not settings.deepseek_enabled:
            return False, "DeepSeek-V4.1-Flash 已在配置中关闭"
        request = urllib.request.Request(self._url("/models"), headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=settings.deepseek_ready_timeout) as response:
                if 200 <= response.status < 300:
                    return True, None
                return False, f"上游返回 HTTP {response.status}"
        except Exception as exc:
            return False, f"上游不可达：{exc}"

    def open_request(self, path: str, body: dict, extra_headers: dict[str, str] | None = None):
        """发起上游请求并返回未读取的响应对象，由调用方负责 close()。"""
        payload = dict(body)
        if settings.deepseek_upstream_model:
            payload["model"] = settings.deepseek_upstream_model
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = self._headers()
        for name, value in (extra_headers or {}).items():
            # 客户端不能覆盖上游鉴权和请求体相关的头。
            if name.lower() not in {"authorization", "content-type", "content-length", "host"}:
                headers[name] = value
        request = urllib.request.Request(
            self._url(path),
            data=data,
            headers=headers,
            method="POST",
        )
        return urllib.request.urlopen(request, timeout=settings.deepseek_timeout)

    def open_chat(self, body: dict, extra_headers: dict[str, str] | None = None):
        return self.open_request("/chat/completions", body, extra_headers)

    def open_messages(self, body: dict, extra_headers: dict[str, str] | None = None):
        return self.open_request("/messages", body, extra_headers)


deepseek_backend = DeepSeekBackend()
