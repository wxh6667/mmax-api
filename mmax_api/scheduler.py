import queue
import threading
import traceback
from collections.abc import Callable

from .jobs import jobs


class GPUScheduler:
    """单 GPU FIFO 调度器；任何时刻只执行一个生成任务。"""

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, Callable[[str], str]]] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="mmax-gpu-worker", daemon=True)
        self._thread.start()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def submit(self, job_id: str, fn: Callable[[str], str]) -> None:
        self._queue.put((job_id, fn))

    def _run(self) -> None:
        while True:
            job_id, fn = self._queue.get()
            try:
                jobs.update(job_id, status="in_progress", progress=1)
                output_path = fn(job_id)
                jobs.finish(job_id, output_path)
            except Exception as exc:
                traceback.print_exc()
                jobs.fail(job_id, "generation_failed", str(exc))
            finally:
                self._queue.task_done()


scheduler = GPUScheduler()
