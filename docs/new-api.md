# New API 接入说明

本项目不在服务端实现 New API 专用兼容路由。`mmax-api` 只提供稳定的图片与视频能力协议，New API 负责声明模型能力和路由。

## 推荐拓扑

同一个 `mmax-api` Base URL 和同一个 API Key，在 New API 中拆成两个渠道：

```text
New API
├── Krea 渠道：Advanced Custom
│   └── krea-2-turbo -> OpenAI Images
└── H3 渠道：Task Plugin
    └── minimax-h3 -> OpenAI Video
```

这样两个模型不会再依赖模型名猜测类型，也不需要改名成 `dall-e`、`flux` 或 `sora-2`。

## Krea 2 Turbo

渠道类型选择 **Advanced Custom**，模型只填写：

```text
krea-2-turbo
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
      "models": ["krea-2-turbo"],
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
      "models": ["krea-2-turbo"],
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

`/v1/images/generations` 是 New API 自身用于 `image-generation` 类型识别的标准端点。`/v1/images/edits` 用于单参考图编辑。

## MiniMax H3

H3 使用 New API 的 **Task Plugin** 渠道，不使用模型名别名。

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

## H3 条件输入

`POST /v1/videos` 同时支持 JSON 和 multipart。

标准/核心字段：

```text
model             minimax-h3
prompt            提示词
seconds           4 / 8 / 12
size              1280x720 / 720x1280 / 1792x1024 / 1024x1792
seed              可选整数
input_reference   首帧，可为上传文件、URL 或 data:image
end_reference     尾帧，可为上传文件、URL 或 data:image
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

## Krea 条件输入

文生图：

```text
POST /v1/images/generations
```

单参考图编辑：

```text
POST /v1/images/edits
```

Krea 编辑支持：

```text
image       1 张参考图
prompt      编辑提示词
strength    0~1，默认 0.65；越高改动越大
size        输出尺寸
seed        可选
n           1~4
```

当前 DiffSynth Krea2 计算链只有单个 `input_image` latent，因此明确限制为 **1 张参考图**。Mask 局部编辑和多参考图目前不支持。

## 图片响应

`/v1/images/generations` 和 `/v1/images/edits` 是同步响应，支持：

```text
response_format=url
response_format=b64_json
```

`url` 模式返回自包含的 `data:image/png;base64,...` URL，因此即使 `mmax-api` 位于 New API 后面的内网地址，最终客户端仍然能直接显示图片，不需要访问 mmax 的内部地址。
