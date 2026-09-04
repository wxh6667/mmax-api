import threading
import time
import uuid
from copy import deepcopy
from typing import Any


class JobStore:
    """进程内任务状态存储。服务重启后任务状态会清空。"""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def create(self, kind: str, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        prefix = "video" if kind == "video" else "image"
        job_id = f"{prefix}_{uuid.uuid4().hex}"
        now = int(time.time())
        job = {
            "id": job_id,
            "object": kind,
            "model": model,
            "status": "queued",
            "progress": 0,
            "created_at": now,
            "completed_at": None,
            "error": None,
            "output_path": None,
            "payload": payload,
        }
        with self._lock:
            self._jobs[job_id] = job
        return deepcopy(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job else None

    def update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(changes)

    def finish(self, job_id: str, output_path: str) -> None:
        self.update(
            job_id,
            status="completed",
            progress=100,
            completed_at=int(time.time()),
            output_path=output_path,
        )

    def fail(self, job_id: str, code: str, message: str) -> None:
        self.update(
            job_id,
            status="failed",
            progress=100,
            completed_at=int(time.time()),
            error={"code": code, "message": message},
        )


jobs = JobStore()
