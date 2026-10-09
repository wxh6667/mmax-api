import json
import sqlite3
import threading
import time
import uuid
from copy import deepcopy
from typing import Any

from .config import settings

_COLUMNS = (
    "id", "object", "model", "status", "progress",
    "created_at", "completed_at", "error", "output_path", "payload",
)


class JobStore:
    """任务状态存储：内存为运行时第一来源，SQLite 落盘用于服务重启后恢复。

    已完成任务重启后仍可查询、取回产物（产物文件本就在磁盘）。重启时仍在
    队列或生成中的任务会被标记为 service_restarted 失败——生成进程确实已
    中断，这样轮询方（如 New API）拿到明确终态，而不是 404 被判死。
    payload 中的 PIL Image 对象不落盘，恢复场景只依赖标量字段。
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(settings.runtime_dir / "jobs.db", check_same_thread=False)
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    object TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    error TEXT,
                    output_path TEXT,
                    payload TEXT
                )
                """
            )
            self._mark_interrupted()
            self._db.commit()

    def _mark_interrupted(self) -> None:
        """把上次进程遗留的未完成任务标记为明确失败。"""
        pending = self._db.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'in_progress')"
        ).fetchone()[0]
        if not pending:
            return
        self._db.execute(
            "UPDATE jobs SET status = 'failed', progress = 100, completed_at = ?, error = ?"
            " WHERE status IN ('queued', 'in_progress')",
            (
                int(time.time()),
                json.dumps(
                    {"code": "service_restarted", "message": "服务重启，任务已中断。"},
                    ensure_ascii=False,
                ),
            ),
        )
        print(f"===== 恢复任务状态：{pending} 个未完成任务已标记为 service_restarted =====", flush=True)

    def _persist(self, job: dict[str, Any]) -> None:
        """整行落盘；PIL Image 等不可序列化对象降级为 None。"""
        self._db.execute(
            "INSERT OR REPLACE INTO jobs (id, object, model, status, progress,"
            " created_at, completed_at, error, output_path, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job["id"],
                job["object"],
                job["model"],
                job["status"],
                job["progress"],
                job["created_at"],
                job.get("completed_at"),
                json.dumps(job["error"], ensure_ascii=False) if job.get("error") is not None else None,
                job.get("output_path"),
                json.dumps(job.get("payload"), ensure_ascii=False, default=lambda _value: None),
            ),
        )
        self._db.commit()

    def _restore(self, job_id: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT id, object, model, status, progress, created_at, completed_at,"
            " error, output_path, payload FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        job = dict(zip(_COLUMNS, row))
        job["error"] = json.loads(job["error"]) if job["error"] is not None else None
        job["payload"] = json.loads(job["payload"]) if job["payload"] is not None else {}
        return job

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
            self._persist(job)
        return deepcopy(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                # 重启后内存为空：从 SQLite 恢复（payload 中的图片对象已丢弃）。
                job = self._restore(job_id)
                if job is None:
                    return None
                self._jobs[job_id] = job
            return deepcopy(job)

    def update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(changes)
            self._persist(self._jobs[job_id])

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
