# 调研：New API 消费方契约（对 mmax-api 服务端的影响）

来源：QuantumNous/new-api（49.5k stars，AGPL-3.0，Go）源码研读，基线 v1.0.0-rc.42（2026-10-08）。
调研日期：2026-10-09。背景：优化主体是 mmax-api（能力输出方），New API 只是消费方。

## 关键版本事实

- JS Task Plugin 体系由 v1.0.0-rc.27（2026-08-29，PR #7076）引入，替换了旧内置 task adaptor，属破坏性变更。
- 我们走的链路：客户端 → New API `/v1/videos`（openai_video 协议）→ Task Plugin 渠道（type 61）→ mmax-api `/v1/videos`。
- OpenAI 官方 Videos API 已于 2026-09-24 永久关闭；New API 的 openai_video 协议是当前事实上的活跃标准。

## New API 调用 mmax-api 的完整生命周期

1. **submit**：`POST {baseUrl}/v1/videos`（JSON 或 multipart），任何 2xx 视为提交成功，`parseSubmitResponse` 从响应取 `id`。提交时预扣费。
2. **poll**：后台轮询（`service/task_polling.go`）`GET {baseUrl}/v1/videos/{id}`，`parseTaskResult` 解析 `{status, progress, reason}`。
   - **HTTP 分类**：2xx 正常解析；**404/410 → 立即判 FAILURE 并退款**；401/403 不动状态只计失败；其他错误连续 `TASK_POLL_MAX_FAILURES`（默认 20）次 → FAILURE 退款；**24h 超时兜底 FAILURE**。
   - `status:"UNKNOWN"` 会被原样上报，不应做 `|| "IN_PROGRESS"` 兜底。
3. **retrieve**：`GET /v1/videos/{task_id}` 只渲染 New API 持久化的 data 快照，不触发上游实时查询。
4. **content**：`controller.VideoProxy` 按 `buildContentRequest` 描述符请求上游 `{baseUrl}/v1/videos/{id}/content`，流式 `io.Copy` 回写，**转发 Range/206/HEAD**，复制上游 Content-Type 等响应头。
5. **计费**：表达式计费 `u("seconds")` 等 usageSchema facts，提交时按 `extractUsage` 预留，完成时 `extractUsageOnComplete` 按实测 facts 多退少补（sora 模式：按上游返回的实际 seconds/size 结算）。

## 对 mmax-api 服务端的硬性要求 / 差距

| # | 消费方行为 | mmax-api 现状 | 差距 |
|---|---|---|---|
| 1 | 轮询 404 → 立即 FAILURE + 退款；20 次失败 → FAILURE | `JobStore` 纯内存，`update.sh` 重启/崩溃后所有任务 404 | **任务态不持久 = 重启即判死**，GPU 在跑/已出片也取不回 |
| 2 | 完成时按响应中实测 seconds/size 结算计费 | `_public_job` 剔除 payload，完成响应无 seconds/size | 计费只能按提交估算，无法纠正 |
| 3 | progress int 0-100（OpenAI 语义：完成百分比） | H3 仅 5→85→92 三档 | 生成期客户端长期只见 5% |
| 4 | content 代理转发 Range/206（在线播放拖进度条） | `FileResponse`（Starlette）Range 支持需核对 | 疑似不支持 Range |
| 5 | 状态枚举 queued/in_progress/completed/failed | 完全一致 | 无 |
| 6 | `parseTaskResult` 失败时读 `error.message` | `error={code,message}` | 无 |

## 官方示例（sora 插件，plugins/tasks/sora/plugin.js）

与我们 plugin.js 同构；差异：多导出 `extractUsageOnComplete`（从任务完成响应读实测 seconds/size 纠正计费）——依赖上游（即 mmax-api）在完成响应里返回这两个字段。插件侧是否补此导出属于次要决策，服务端先补字段。

## 关键链接

- 插件契约文档：docs/plugin-api/v1.md、v1.d.ts、v1.schema.json（仓库内）
- 必需导出校验：pkg/jsplugin/registry.go#L342-L354
- 提交侧 ctx：relay/channel/task/jsplugin/adaptor.go#L1359-L1477
- 客户端枚举：relaykit/dto/openai_video.go#L7-L13（queued/in_progress/completed/failed）
- render 输出 host 强制覆写 id/object/model/status/progress/created_at：adaptor.go#L930-L944
- 轮询调度：service/task_polling.go；视频代理：controller/video_proxy.go
- 计费：relay/relay_task.go#L259-L330、pkg/billingexpr/expr.md
