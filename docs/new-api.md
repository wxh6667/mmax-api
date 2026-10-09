# New API 接入说明

本项目不在服务端实现 New API 专用兼容路由。`mmax-api` 只提供稳定的图片与视频能力协议，New API 负责声明模型能力和路由。

## 推荐拓扑

同一个 `mmax-api` Base URL 和同一个 API Key，在 New API 中拆成两个渠道：

```text
New API
├── HiDream 渠道：Advanced Custom
│   └── hidream-o1-image -> OpenAI Images
└── H3 渠道：Task Plugin
    └── minimax-h3 -> OpenAI Video
```

这样两个模型不依赖模型名猜测类型，也不需要改名成 `dall-e`、`flux` 或 `sora-2`。

## MiniMax H3

H3 使用 New API 的 **Task Plugin** 渠道（New API v1.0.0-rc.27+ 的 JS Task Plugin 体系），不使用模型名别名。

插件文件：

```text
integrations/new-api/minimax-h3/plugin.js
```

插件 Key：

```text
mmax-h3
```

模型名：

```text
minimax-h3
```

在 New API 管理后台的任务插件页面，可以上传该 `plugin.js`，也可以使用 GitHub Raw 地址安装：

```text
https://raw.githubusercontent.com/wxh6667/mmax-api/main/integrations/new-api/minimax-h3/plugin.js
```

然后新建 **Task Plugin** 渠道：

```text
Task Plugin Key: mmax-h3
Base URL:        mmax-api 的地址
API Key:         mmax/.api_key 中的 Key
Model:           minimax-h3
```

该插件只声明和转发标准 OpenAI Video 协议：

```text
POST /v1/videos
GET  /v1/videos/{video_id}
GET  /v1/videos/{video_id}/content
```

### H3 条件输入

`POST /v1/videos` 同时支持 JSON 和 multipart。

标准/核心字段：

```text
model             minimax-h3
prompt            提示词
seconds           1~15 秒
size              1280x720 / 720x1280 / 1792x1024 / 1024x1792
seed              可选整数
steps             可选，默认 20
input_reference   首帧，可为上传文件、URL 或 data:image
end_reference     尾帧，同上
```

JSON 还支持任意关键帧：

```json
{
  "model": "minimax-h3",
  "prompt": "镜头缓慢推进",
  "seconds": 4,
  "size": "1280x720",
  "keyframes": [
    {"image": "https://example.com/a.png", "index": 20},
    {"image": "data:image/png;base64,...", "index": 60}
  ]
}
```

`index=-1` 表示最后一帧。

当前服务器使用 FL2VA checkpoint，因此这里的参考图能力是**帧条件**。独立的 Ref2VA“参考人物/风格图但不作为视频帧”需要另一套 Ref2VA 权重，当前部署没有启用，所以不会在能力列表中虚报支持。

### 计费

插件通过 `usageSchema` 声明 `seconds`（数值，秒）和 `size`（尺寸枚举）两个计费事实。New API 的表达式计费可以直接引用它们：

```text
tier("base", u("seconds") * 0.4)
```

上面表示每秒 $0.40；`size` 枚举可用于分档表达式（例如大尺寸更贵）。

计费流程与 sora 一致：提交时按请求中的 `seconds`/`size` 预留额度，任务完成后按 `GET /v1/videos/{id}` 响应中的实测 `seconds`/`size` 结算，多退少补。mmax-api 的任务响应（提交返回、轮询返回）都包含这两个字段。

### 任务状态与重启

任务状态由 mmax-api 持久化在本地 SQLite（`runtime/jobs.db`）。服务重启后：

- 已完成任务仍可查询、仍可通过 `/content` 取回视频；
- 重启时未完成的任务会立刻返回 `failed`（错误码 `service_restarted`），轮询方拿到明确终态，不会 404。

生成期间 `progress` 按去噪步数推进（5~90），可用于展示真实进度。

## HiDream-O1-Image

图片模型走 **Advanced Custom** 渠道，模型只填写：

```text
hidream-o1-image
```

Base URL 指向 `mmax-api`，Key 使用 `mmax/.api_key` 中的 Bearer Key。

Advanced Custom 路由建议：

```json
{
  "advanced_routes": [
    {
      "incoming_path": "/v1/images/generations",
      "upstream_path": "/v1/images/generations",
      "converter": "none",
      "models": ["hidream-o1-image"],
      "auth": {
        "type": "header",
        "name": "Authorization",
        "value": "Bearer {api_key}"
      }
    },
    {
      "incoming_path": "/v1/images/edits",
      "upstream_path": "/v1/images/edits",
      "converter": "none",
      "models": ["hidream-o1-image"],
      "auth": {
        "type": "header",
        "name": "Authorization",
        "value": "Bearer {api_key}"
      }
    },
    {
      "incoming_path": "/v1/models",
      "upstream_path": "/v1/models",
      "converter": "none",
      "models": [],
      "auth": {
        "type": "header",
        "name": "Authorization",
        "value": "Bearer {api_key}"
      }
    }
  ]
}
```

`/v1/images/generations` 是 New API 自身用于 `image-generation` 类型识别的标准端点。`/v1/images/edits` 用于参考图编辑。

### 图片能力

```text
POST /v1/images/generations   文生图
POST /v1/images/edits         单图指令编辑 / 2~10 张多参考主体驱动
```

两个接口都支持：

```text
prompt            提示词（edits 必填）
negative_prompt   可选负向提示词
size              输出尺寸，默认 1024x1024，最大 2048x2048（宽高为 16 的倍数）
seed              可选整数
n                 1~4
steps             可选，默认 50
cfg_scale         可选，默认 4.0
shift             可选；多参考主体驱动默认 1.0，其余默认 3.0
noise_scale       可选，默认 8.0
```

`edits` 的 `image` 字段可重复传 1~10 张参考图（上传文件、URL 或 data:image 均可）。单图编辑可传 `keep_original_aspect=true` 保持原图宽高比。不支持 mask 局部编辑。

## 图片响应

`/v1/images/generations` 和 `/v1/images/edits` 是同步响应，支持：

```text
response_format=url
response_format=b64_json
```

`url` 模式返回自包含的 `data:image/png;base64,...` URL，因此即使 `mmax-api` 位于 New API 后面的内网地址，最终客户端仍然能直接显示图片，不需要访问 mmax 的内部地址。
