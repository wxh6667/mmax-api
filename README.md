# mmax-api

`mmax-api` 是一个面向本地 GPU 推理的统一 FastAPI 服务，目前整合：

- **MiniMax H3**：视频 + 原生立体声音频生成
- **Krea 2 Turbo**：图片生成与单参考图编辑

两个模型共用一个对外端口和一个 FIFO GPU 任务队列，单张 GPU 上任何时刻只运行一个生成任务，避免显存争抢。

> 本仓库只提供服务代码、部署脚本和配置模板，不分发模型权重。模型文件需要使用者自行准备，并遵守各自上游许可证。

## 核心接口

默认端口：`6006`。

```text
GET  /health

GET  /v1/models
GET  /v1/models/{model_id}

POST /v1/images/generations
POST /v1/images/edits
GET  /v1/images/{image_id}
GET  /v1/images/{image_id}/content

POST /v1/videos
GET  /v1/videos/{video_id}
GET  /v1/videos/{video_id}/content
```

所有 `/v1/*` 接口都需要：

```text
Authorization: Bearer <你的 API Key>
```

`/health` 不需要鉴权。

## 模型能力

### Krea 2 Turbo

当前支持：

- 文生图
- 单参考图图生图 / 编辑
- `strength` 控制参考图保留程度
- `n=1~4`
- `response_format=url` 或 `b64_json`

当前不支持：

- 多参考图
- mask 局部编辑

DiffSynth 当前 Krea2 计算链内部已经存在 `input_image` latent 路径，但上游 `Krea2Pipeline.__call__()` 尚未公开该参数；本项目直接调用同一原生 pipeline 单元链，把这项能力暴露出来，不引入额外模型或第三方编辑算法。

### MiniMax H3

当前支持：

- 文生视频 + 原生音频
- 首帧图生视频
- 尾帧约束
- 首尾帧组合
- JSON 任意关键帧 `keyframes[{image,index}]`
- JSON 和 multipart 两种请求格式

当前部署使用 FL2VA checkpoint，因此这里的参考图能力属于**视频帧条件**。独立的 Ref2VA“人物/风格参考图但不作为视频帧”需要另一套 Ref2VA 权重，当前没有启用。

## 架构

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

Krea 使用 CPU RAM offload；H3 使用 DiffSynth 的低显存管理。模型可以同时留在同一个进程中，但推理不会并发抢 GPU。

## 服务器目录

推荐：

```text
/root/autodl-tmp/
├── mmax/
│   ├── .venv/
│   ├── .deps/DiffSynth-Studio/
│   ├── mmax_api/
│   ├── integrations/
│   ├── docs/
│   ├── scripts/
│   ├── runtime/
│   ├── .env
│   └── .api_key
├── models/
│   ├── h3/
│   └── krea2/
└── outputs/
    ├── videos/
    └── images/
```

## 安装与迁移

旧 AutoDL H3 环境迁移：

```bash
cd /root/autodl-tmp
git clone https://github.com/wxh6667/mmax-api.git mmax
cd mmax
bash scripts/migrate_legacy.sh
```

准备 Krea：

```bash
/root/autodl-tmp/mmax/.venv/bin/python scripts/prepare_krea.py
```

启动：

```bash
bash scripts/start.sh
bash scripts/healthcheck.sh
```

确认两个模型都生成成功以后，可以清理旧 H3 / ComfyUI：

```bash
bash scripts/cleanup_legacy.sh
```

全新安装：

```bash
cd /root/autodl-tmp
git clone https://github.com/wxh6667/mmax-api.git mmax
cd mmax
cp .env.example .env
bash scripts/install.sh
```

## 运行管理

启动：

```bash
bash scripts/start.sh
```

停止：

```bash
bash scripts/stop.sh
```

重启：

```bash
bash scripts/restart.sh
```

健康检查：

```bash
bash scripts/healthcheck.sh
```

实时日志：

```bash
bash scripts/logs.sh
```

只看最近错误：

```bash
bash scripts/logs.sh --errors
```

更新：

```bash
bash scripts/update.sh
```

`update.sh` 会执行 `git pull --ff-only`、Python 语法检查、重启和健康检查。

## Krea 文生图

```bash
curl -X POST http://127.0.0.1:6006/v1/images/generations \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "krea-2-turbo",
    "prompt": "雨夜东京街头的一辆黑色跑车，电影摄影",
    "size": "1024x1024",
    "seed": 42,
    "response_format": "b64_json"
  }'
```

Krea Turbo 固定使用：

```text
num_inference_steps = 8
cfg_scale = 1
mu = 1.15
```

## Krea 参考图编辑

```bash
curl -X POST http://127.0.0.1:6006/v1/images/edits \
  -H "Authorization: Bearer $KEY" \
  -F 'model=krea-2-turbo' \
  -F 'prompt=改成夜晚霓虹灯环境，保持主体构图' \
  -F 'size=1024x1024' \
  -F 'strength=0.55' \
  -F 'response_format=b64_json' \
  -F 'image=@reference.png'
```

`strength` 范围 `(0, 1]`，越高改动越大，默认 `0.65`。

## H3 文生视频

JSON：

```bash
curl -X POST http://127.0.0.1:6006/v1/videos \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "minimax-h3",
    "prompt": "雨夜街头的电影镜头，人物自然说话",
    "seconds": 4,
    "size": "1280x720",
    "seed": 42
  }'
```

返回任务后：

```text
GET /v1/videos/{id}
GET /v1/videos/{id}/content
```

## H3 首帧 / 尾帧

multipart 上传首尾帧：

```bash
curl -X POST http://127.0.0.1:6006/v1/videos \
  -H "Authorization: Bearer $KEY" \
  -F 'model=minimax-h3' \
  -F 'prompt=镜头从第一张图自然过渡到最后一张图' \
  -F 'seconds=4' \
  -F 'size=1280x720' \
  -F 'input_reference=@first.png' \
  -F 'end_reference=@last.png'
```

也可以在 JSON 中使用 URL 或 `data:image`：

```json
{
  "model": "minimax-h3",
  "prompt": "镜头缓慢推进",
  "seconds": 4,
  "size": "1280x720",
  "input_reference": "https://example.com/first.png",
  "end_reference": "data:image/png;base64,..."
}
```

## H3 任意关键帧

JSON：

```json
{
  "model": "minimax-h3",
  "prompt": "人物从室内走到窗边",
  "seconds": 4,
  "size": "1280x720",
  "keyframes": [
    {"image": "https://example.com/frame-a.png", "index": 20},
    {"image": "https://example.com/frame-b.png", "index": 60}
  ]
}
```

`index=-1` 表示最后一帧。首帧、尾帧和 `keyframes` 不能使用重复的帧索引。

## New API

New API 不会依据 `/v1/models` 返回的 `type` 自动判断模型类别。推荐让网关显式声明能力：

- Krea：Advanced Custom -> `image-generation`
- H3：Task Plugin -> `openai_video`

详细配置：

```text
docs/new-api.md
```

H3 可选任务插件：

```text
integrations/new-api/minimax-h3/plugin.js
```

## 运行说明

- 任务状态当前保存在进程内存中，重启 API 后历史任务状态会清空，但输出文件保留。
- uvicorn 必须使用 `--workers 1`，否则会出现多个独立 GPU 队列和模型实例。
- H3 默认使用当前服务器已验证的 `10 steps`，可通过 `MMAX_H3_STEPS` 修改。
- Krea 图片宽高必须能被 16 整除。
- 默认图片最大像素约为 `2048 × 2048`，可通过环境变量调整。

## 上游项目

- DiffSynth-Studio：<https://github.com/modelscope/DiffSynth-Studio>
- ComfyUI：<https://github.com/Comfy-Org/ComfyUI>

本仓库服务代码采用 MIT License；模型权重仍受各自上游许可证约束。
