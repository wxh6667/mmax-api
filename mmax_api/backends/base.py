from abc import ABC, abstractmethod


class Backend(ABC):
    """模型后端统一接口。"""

    model_id: str
    kind: str

    @abstractmethod
    def ready(self) -> tuple[bool, str | None]:
        """返回模型文件是否已准备完成。"""
        raise NotImplementedError

    @abstractmethod
    def generate(self, job_id: str, payload: dict) -> str:
        """执行生成并返回最终输出文件路径。"""
        raise NotImplementedError
