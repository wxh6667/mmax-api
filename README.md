# mmax-api

`mmax-api` 是一个面向本地 GPU 推理的统一 FastAPI 服务，目前整合：

- **MiniMax H3**：视频 + 原生音频生成
- **Krea 2 Turbo**：图片生成

两个模型共用一个对外端口和一个 FIFO GPU 任务队列，避免在单张显卡上同时推理导致显存争抢或进程崩溃。

> 本仓库只提供服务代码、部署脚本和配置模板，不分发任何模型权重。模型文件需要使用者自行准备，并遵守对应模型的许可证。

## 接口

默认端口为 `6006`：

```text
GET  /health

GET  /v1/models
GET  /v1/models/{model_id}

POST /v1/videos
GET  /v1/videos/{video_id}
GET  /v1/videos/{video_id}/content

POST /v1/images
GET  /v1/images/{image_id}
GET  /v1/images/{image_id}/content
```

所有 `/v1/*` 接口都需要：

```text
Authorization: Bearer <你的 API Key>
```

`/health` 不需要鉴权，便于本机健康检查和进程守护。

## 架构

HTTP 请求进入后立即创建 `queued` 任务，由唯一的后台 GPU worker 按提交顺序执行：

```text
HTTP 请求
   ↓
统一 FIFO 队列
   ↓
唯一 GPU Worker
   ├── MiniMax H3
   └── Krea 2 Turbo
   ↓
outputs
```

模型可以通过 DiffSynth 的显存管理保留 CPU / 磁盘 offload 状态，但任何时刻只允许一个生成任务真正使用 GPU。

## 最终服务器目录

推荐整理为：

```text
/root/autodl-tmp/
├── mmax/                  # 本仓库
│   ├── .venv/             # 独立 Python 环境
│   ├── .deps/
│   │   └── DiffSynth-Studio/
│   ├── mmax_api/
│   ├── scripts/
│   └── runtime/
├── models/
│   ├── h3/
│   └── krea2/
└── outputs/
    ├── videos/
    └── images/
```

API 代码、Python 环境、DiffSynth、模型和输出彼此分离，旧 `/root/autodl-tmp/h3` 和 ComfyUI 最终可以完全删除。

## 当前 AutoDL 服务器迁移

如果服务器上已经有旧的 H3 API 和 ComfyUI Krea 权重，推荐按下面顺序迁移。

先克隆本仓库：

```bash
cd /root/autodl-tmp
git clone https://github.com/wxh6667/mmax-api.git mmax
cd mmax
```

然后执行旧 H3 迁移：

```bash
bash scripts/migrate_legacy.sh
```

这个脚本会：

1. 停止旧 H3 `6006` 服务；
2. 把旧 API Key 迁移到 `mmax/.api_key`；
3. 把旧 `venv` 原地移动成 `mmax/.venv`；
4. 把旧 `DiffSynth-Studio` 原地移动到 `mmax/.deps/`；
5. 把 H3 模型原地移动到 `/root/autodl-tmp/models/h3/`；
6. 不复制大模型文件，因此不会临时多占一份 H3 磁盘空间。

接着准备 Krea 2：

```bash
/root/autodl-tmp/mmax/.venv/bin/python scripts/prepare_krea.py
```

Krea 准备完成后启动统一 API：

```bash
bash scripts/start.sh
bash scripts/healthcheck.sh
```

确认 H3 视频和 Krea 图片都能正常生成以后，可以删除旧目录：

```bash
bash scripts/cleanup_legacy.sh
```

清理脚本只有在新的 H3/Krea 模型、Python 环境和 DiffSynth 都已经存在时才会执行删除。

## 全新安装

如果不是从旧服务器迁移，可以直接：

```bash
cd /root/autodl-tmp
git clone https://github.com/wxh6667/mmax-api.git mmax
cd mmax
cp .env.example .env
bash scripts/install.sh
```

`install.sh` 会创建独立 `.venv`，并把 DiffSynth-Studio 放在 `mmax/.deps/DiffSynth-Studio`。模型仍需要自行准备到 `.env` 指定的位置。

## 准备 Krea 2

当前迁移脚本默认读取这两个已有 ComfyUI FP8 文件：

```text
/root/autodl-tmp/imagegen/ComfyUI/models/diffusion_models/krea2_turbo_fp8_scaled.safetensors
/root/autodl-tmp/imagegen/ComfyUI/models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors
```

执行：

```bash
/root/autodl-tmp/mmax/.venv/bin/python scripts/prepare_krea.py
```

脚本会：

1. 识别旧版 `_quantization_metadata` 和新版 `.comfy_quant` 两种 ComfyUI FP8 格式；
2. 将 Krea DiT 和 Qwen3-VL 权重一次性反量化为普通 BF16 safetensors；
3. 只补齐 Qwen3-VL tokenizer/config；
4. 下载官方 Qwen Image VAE；
5. 将最终文件整理到 `/root/autodl-tmp/models/krea2/`。

这样新 API 运行时不再依赖 ComfyUI，也不依赖 ComfyUI 的量化 runtime。

## 启动、停止和更新

启动：

```bash
bash scripts/start.sh
bash scripts/healthcheck.sh
```

查看日志：

```bash
tail -f runtime/api.log
```

停止和重启：

```bash
bash scripts/stop.sh
bash scripts/restart.sh
```

从 GitHub 更新：

```bash
bash scripts/update.sh
```

`update.sh` 会执行 `git pull --ff-only`、Python 语法检查、服务重启和 `/health` 检查。

## 视频生成

```bash
curl -X POST http://127.0.0.1:6006/v1/videos \
  -H "Authorization: Bearer $KEY" \
  -F 'model=minimax-h3' \
  -F 'prompt=雨夜街头的电影镜头，一名年轻男子看向镜头并说话' \
  -F 'seconds=4' \
  -F 'size=1280x720'
```

返回任务 ID 后轮询：

```text
GET /v1/videos/{id}
```

完成后下载：

```text
GET /v1/videos/{id}/content
```

### 首帧和尾帧

H3 接口支持：

```text
input_reference   首帧
image_tail        尾帧
```

同时兼容 `image`、`first_frame`、`image_start`、`last_frame`、`end_frame`、`image_end` 等常见别名。首尾帧在 DiffSynth 中使用 `[0, -1]` 作为 keyframe 索引。

## 图片生成

```bash
curl -X POST http://127.0.0.1:6006/v1/images \
  -H "Authorization: Bearer $KEY" \
  -F 'model=krea-2-turbo' \
  -F 'prompt=一辆黑色跑车停在雨夜东京街头，电影摄影' \
  -F 'size=1024x1024'
```

也支持 JSON 请求体。

Krea 2 Turbo 固定使用官方 Turbo 参数：

```text
num_inference_steps = 8
cfg_scale = 1
mu = 1.15
```

任务状态：

```text
GET /v1/images/{id}
```

图片下载：

```text
GET /v1/images/{id}/content
```

## 运行说明

- 任务状态目前保存在进程内存中，服务重启后历史任务状态会清空，但已生成文件不会被删除。
- uvicorn 必须使用 `--workers 1`，否则每个 worker 都会创建自己的 GPU 队列和模型实例。
- H3 默认保留当前服务器已经验证稳定的 `10 steps`，可通过 `MMAX_H3_STEPS` 修改。
- Krea 图片宽高必须能被 16 整除。
- 默认限制最大约 `2048 × 2048` 像素，可通过环境变量调整。
- Qwen Image VAE 使用官方模型文件，不复用当前服务器中 hash 识别异常的 ComfyUI VAE 文件。

## 上游项目

- DiffSynth-Studio：<https://github.com/modelscope/DiffSynth-Studio>
- ComfyUI：<https://github.com/Comfy-Org/ComfyUI>

本仓库的服务代码采用 MIT License；模型权重仍受各自上游许可证约束。
