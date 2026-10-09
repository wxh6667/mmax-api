# 技术栈

- Python >=3.10；FastAPI + uvicorn[standard]、python-multipart、Pillow、safetensors（见 pyproject.toml）。
- **DiffSynth-Studio 是隐式核心依赖**：不在 pyproject 里，由 `scripts/install.sh` clone `https://github.com/modelscope/DiffSynth-Studio` 到 `.deps/` 并 `pip install -e`。两个模型后端都 `from diffsynth...` 懒导入。
- H3 后处理依赖系统 `ffmpeg`（lanczos 放大 + unsharp 锐化 + libx264/aac 封装），非 pip 依赖。
- 无测试框架、无 linter/formatter 配置；CI（`.github/workflows/syntax.yml`）只做 compileall / bash -n / node --check 语法检查。
- H3 权重为 NF4 量化（disk offload）；HiDream 为 BF16（CPU offload，按 `torch.cuda.mem_get_info` 动态定显存预算，任务后默认卸载权重）。
- 部署目标 AutoDL 容器（Linux，venv 在 `<root>/.venv`）。
