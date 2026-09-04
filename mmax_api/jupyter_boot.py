"""AutoDL 普通容器实例的 Jupyter Server 自启动扩展。

AutoDL 会在容器启动时自动拉起 JupyterLab。本扩展随 Jupyter Server
加载，并在后台调用 mmax 的 boot.sh，从而实现 6006 API 无人登录自启动。
"""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path("/root/autodl-tmp/mmax")
BOOT_SCRIPT = ROOT / "scripts" / "boot.sh"
LOG_FILE = ROOT / "runtime" / "jupyter-autostart.log"


def _jupyter_server_extension_points():
    """向 Jupyter Server 声明扩展入口。"""
    return [{"module": "mmax_api.jupyter_boot"}]


def _load_jupyter_server_extension(serverapp) -> None:
    """Jupyter Server 启动时异步拉起 mmax-api。"""
    if not BOOT_SCRIPT.exists():
        serverapp.log.warning("mmax-api 自启动脚本不存在：%s", BOOT_SCRIPT)
        return

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            ["bash", str(BOOT_SCRIPT)],
            cwd=str(ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    serverapp.log.info("mmax-api 自启动扩展已加载：%s", BOOT_SCRIPT)
