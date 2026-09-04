"""mmax-api 生产启动入口。

在导入 Uvicorn 前包装 stdout/stderr，让 Uvicorn、DiffSynth、模型后端和 traceback
统一使用北京时间日志前缀。保持单进程单 worker，避免创建多个 GPU 调度器。
"""

from __future__ import annotations

import io
import os
import re
import sys
import threading
from datetime import datetime
from zoneinfo import ZoneInfo


BEIJING = ZoneInfo("Asia/Shanghai")
_LINE_BREAK_RE = re.compile(r"(\r\n|\r|\n)")


class BeijingTimestampStream(io.TextIOBase):
    """给文本流的每一行增加北京时间前缀。"""

    def __init__(self, stream):
        self._stream = stream
        self._line_start = True
        self._lock = threading.RLock()

    @staticmethod
    def _prefix() -> str:
        now = datetime.now(BEIJING)
        return now.strftime("[%Y-%m-%d %H:%M:%S CST+0800] ")

    def write(self, text):
        if not text:
            return 0
        with self._lock:
            for part in _LINE_BREAK_RE.split(str(text)):
                if not part:
                    continue
                if part in {"\r", "\n", "\r\n"}:
                    self._stream.write(part)
                    self._line_start = True
                    continue
                if self._line_start:
                    self._stream.write(self._prefix())
                    self._line_start = False
                self._stream.write(part)
            self._stream.flush()
        return len(text)

    def flush(self):
        with self._lock:
            self._stream.flush()

    def isatty(self):
        return self._stream.isatty()

    def fileno(self):
        return self._stream.fileno()

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._stream, "errors", "strict")


# 必须先替换流，再导入 uvicorn；否则 Uvicorn 的日志 handler 会绑定旧 stderr。
sys.stdout = BeijingTimestampStream(sys.stdout)
sys.stderr = BeijingTimestampStream(sys.stderr)

import uvicorn  # noqa: E402


def main() -> None:
    host = os.getenv("MMAX_HOST", "0.0.0.0")
    port = int(os.getenv("MMAX_PORT", "6006"))
    uvicorn.run(
        "mmax_api.api:app",
        host=host,
        port=port,
        workers=1,
        access_log=True,
    )


if __name__ == "__main__":
    main()
