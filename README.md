# mmax-api

`mmax-api` 是一个面向本地 GPU 推理的统一 FastAPI 服务，目前整合：

- **MiniMax H3**：视频 + 原生立体声音频生成
- **HiDream-O1-Image Full**：文生图、单图指令编辑、多参考主体驱动生成

两个模型共用一个对外端口和一个 FIFO GPU 任务队列；单张 GPU 上任何时刻只运行一个生成任务，避免显存争抢。

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

### HiDream-O1-Image Full

当前支持：

- 文生图
- 单参考图 instruction edit
- 2～10 张多参考 subject-driven 生成
- 单图编辑 `keep_original_aspect`
- `steps` / `cfg_scale` / `shift` / `noise_scale` 请求级覆盖
- `n=1~4`
- `response_format=url` 或 `b64_json`
- 默认最大 `2048x2048`（约 4MP，可通过环境变量调整）

默认参数：

```text
steps       = 50
cfg_scale   = 4.0
shift       = 3.0
noise_scale = 8.0
```

多参考主体驱动在没有显式传 `shift` 时默认使用 `shift=1.0`。

当前不支持：

- mask 局部编辑

### MiniMax H3

当前支持：

- 文生视频 + 原生音频
- 首帧图生视频
- 尾帧约束
- 首尾帧组合
- JSON 任意关键帧 `keyframes[{image,index}]`
- `1～15` 秒时长
- JSON 和 multipart 两种请求格式

当前部署使用 FL2VA checkpoint，因此参考图能力属于**视频帧条件**。独立 Ref2VA“人物/风格参考但不作为视频帧”需要另一套 Ref2VA 权重，当前没有启用。

## 架构

```text
HTTP 请求
   ↓
统一 FIFO 队列
   ↓
唯一 GPU Worker
   ├── MiniMax H3
   └── HiDream-O1-Image Full
   ↓
outputs
```

HiDream 使用 DiffSynth BF16 CPU offload / BF16 GPU 计算，并根据 `MMAX_HIDREAM_VRAM_RESERVE_GB` 自动确定可用显存预算。默认图片任务结束后主动卸载模型权重，确保 H3 可以获得完整显存。

## 服务器目录

推荐：

```text
/root/autodl-tmp/
├── mmax/
│   ├── .venv/
│   ├── .deps/DiffSynth-Studio/
│   ├── mmax_api/
│   ├── integrations/
│   ├── scripts/
│   ├── runtime/
│   ├── .env
│   └── .api_key
├── models/
│   ├── h3/
│   └── hidream-o1-image/
└── outputs/
    ├── videos/
    └── images/
```

## 安装

```bash
cd /root/autodl-tmp
git clone https://github.com/wxh6667/mmax-api.git mmax
cd mmax
cp .env.example .env
bash scripts/install.sh
```

模型权重需另外准备。HiDream 默认路径：

```text
/root/autodl-tmp/models/hidream-o1-image
```

目录内应包含 `model-*.safetensors` 以及模型 processor/config 文件。

## 运行管理

```bash
bash scripts/start.sh
bash scripts/stop.sh
bash scripts/restart.sh
bash scripts/healthcheck.sh
bash scripts/logs.sh
```

更新：

```bash
bash scripts/update.sh
```

`update.sh` 会执行 `git pull --ff-only`、Python 语法检查、重启和健康检查。

## HiDream 文生图

```bash
KEY="$(cat /root/autodl-tmp/mmax/.api_key)"

curl -X POST http://127.0.0.1:6006/v1/images/generations \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hidream-o1-image",
    "prompt": "雨夜上海街头的电影摄影，一位人物站在霓虹灯下",
    "negative_prompt": "模糊，低清晰度，文字，水印",
    "size": "1536x1536",
    "steps": 50,
    "cfg_scale": 4.0,
    "seed": 42,
    "response_format": "b64_json"
  }'
```

## HiDream 单图指令编辑

```bash
KEY="$(cat /root/autodl-tmp/mmax/.api_key)"

curl -X POST http://127.0.0.1:6006/v1/images/edits \
  -H "Authorization: Bearer $KEY" \
  -F 'model=hidream-o1-image' \
  -F 'prompt=把衣服改成深蓝色西装，保持人物身份和构图' \
  -F 'image=@reference.png' \
  -F 'keep_original_aspect=true' \
  -F 'steps=50' \
  -F 'cfg_scale=4.0' \
  -F 'response_format=b64_json'
```

## HiDream 多参考主体驱动

重复传 `image` 字段即可：

```bash
KEY="$(cat /root/autodl-tmp/mmax/.api_key)"

curl -X POST http://127.0.0.1:6006/v1/images/edits \
  -H "Authorization: Bearer $KEY" \
  -F 'model=hidream-o1-image' \
  -F 'prompt=让参考图中的主体一起出现在电影感城市街景中' \
  -F 'image=@ref1.png' \
  -F 'image=@ref2.png' \
  -F 'image=@ref3.png' \
  -F 'size=1536x1536' \
  -F 'response_format=b64_json'
```

## H3 文生视频

```bash
KEY="$(cat /root/autodl-tmp/mmax/.api_key)"

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

## 运行原则

- Uvicorn 必须保持单 worker。
- 图片和视频共用一个 FIFO GPU 队列，不并发抢占显存。
- `/v1/models` 返回当前真实启用模型及能力，网关兼容逻辑不放入核心服务。
- 模型权重不提交到 Git 仓库。
