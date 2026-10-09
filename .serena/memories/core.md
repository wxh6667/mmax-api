# mmax-api 项目总览

单卡 AutoDL GPU 实例上的统一 FastAPI 推理服务（端口 6006），OpenAI 风格 API，整合 MiniMax H3（视频+音频）与 HiDream-O1-Image（图片）。

## 源码地图

- `mmax_api/api.py` — 全部 HTTP 路由、Bearer 鉴权、参数校验、OpenAI 兼容错误体（`APIError`）。项目最大文件，改动入口基本都在这。
- `mmax_api/scheduler.py` — 单线程 FIFO GPU 队列（`GPUScheduler`），任何时刻只跑一个生成任务。
- `mmax_api/jobs.py` — 进程内任务存储（`JobStore`，内存 dict + RLock），**服务重启丢全部任务状态**（设计如此，不做持久化）。
- `mmax_api/config.py` — `MMAX_*` 环境变量 → frozen dataclass `Settings`。
- `mmax_api/backends/` — `base.py` 抽象 `Backend`（`ready()`/`generate()`）；`h3.py`、`hidream.py` 实现。
- `mmax_api/jobs.py` — `JobStore`：内存为运行时第一来源 + SQLite（`runtime/jobs.db`，WAL）写穿透；重启后已完成任务可查可取片，未完成任务标记 `service_restarted` 失败；payload 中 PIL Image 落盘时降级为 None。
- `mmax_api/run.py` — 生产入口：uvicorn **强制单 worker**，导入前包装 stdout/stderr 加北京时间前缀。
- `mmax_api/jupyter_boot.py` — Jupyter Server 扩展，借 AutoDL 自启的 JupyterLab 实现无人登录拉起 `scripts/boot.sh`。
- `scripts/` — AutoDL 部署运维（install/start/stop/healthcheck/update、自启动装卸、legacy 迁移清理）。
- `integrations/new-api/minimax-h3/plugin.js` — New API 网关任务插件，H3 → OpenAI Video 协议。`docs/new-api.md` 是接入文档（含渠道配置与计费表达式说明）。

## 项目不变量

- **单 worker 单 GPU 队列**：图片视频共用一个 FIFO，禁止并发生成抢显存；不得引入多 worker。
- **网关兼容逻辑不进核心服务**：New API 等网关适配放在 `integrations/` 插件层，`mmax_api/` 只提供稳定协议。
- **模型权重与 DiffSynth 不入 Git**：权重在服务器 `/root/autodl-tmp/models/`，DiffSynth-Studio clone 到 `.deps/` 后 `pip install -e`。
- 默认部署根 `/root/autodl-tmp/mmax`，输出 `/root/autodl-tmp/outputs/{videos,images}`。

## 相关记忆

- 技术栈与依赖细节见 `mem:tech_stack`
- 代码约定见 `mem:conventions`
- 常用命令与完成验证见 `mem:suggested_commands` 与 `mem:task_completion`
