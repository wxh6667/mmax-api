# 调研：OpenAI Video API（/v1/videos）最终协议规范

来源：developers.openai.com 官方 API Reference 与 openai-python SDK types（逐字段核对）。
注意：官方 Videos API（Sora 2）已于 2026-09-24 永久关闭，以下为关闭前最终契约，作为 mmax-api 对外协议的对齐目标。

## 端点

- POST /v1/videos（创建）；GET /v1/videos/{id}；GET /v1/videos/{id}/content（二进制流，query 参数 variant=video|thumbnail|spritesheet）
- GET /v1/videos（列表，after/limit/order，返回 {data, first_id, last_id, has_more, object:"list"}）
- DELETE /v1/videos/{id}（**删除已完成/失败任务，非取消**；无 cancel 端点、无 cancelled 状态）
- 后期端点：/remix（弃用）/edits /extensions /characters（mmax 不涉及）

## Video 对象字段（GET /v1/videos/{id}）

```
id: str                       # 任务 id
object: "video"               # 恒为 "video"
created_at: int               # Unix 秒
completed_at: int|null
expires_at: int|null          # 资产过期
status: queued|in_progress|completed|failed   # 无 cancelled
progress: int                 # 完成百分比（文档未写范围，惯例 0-100）
error: {code, message, ...}|null
model: str
prompt: str|null              # 官方在对象里回显 prompt
seconds: str                  # "4"/"8"/"12"（Sora 枚举；mmax 为 1-15 连续）
size: "720x1280"|"1280x720"|"1024x1792"|"1792x1024"
```

## POST /v1/videos 请求体

- prompt 必填；model；seconds（Sora 为字符串枚举）；size；input_reference（multipart 文件或 JSON {image_url|file_id}）。
- 官方不存在：n、stream、input_reference_mask、end_reference（end_reference 是 mmax 扩展，与首尾帧能力对应）。

## 等待与计费

- 轮询建议 10-20 秒间隔 + 指数退避；webhook 仅 video.completed / video.failed。
- 官方按秒计费（sora-2 720p $0.10/s、pro $0.30/s、pro 大尺寸 $0.50/s，2025-12 存档）。

## 对 mmax-api 的对齐结论

已一致：状态枚举、object 类型、二进制 content 端点、prompt 必填。
可补齐（低风险增强）：公开 job 对象中的 `seconds`、`size`、`prompt`（官方有；同时服务 New API 完成时计费结算）。
可选：`expires_at`（本地服务无 TTL，意义不大）、GET /v1/videos 列表与 DELETE（New API 插件链路不用，优先级低）。
