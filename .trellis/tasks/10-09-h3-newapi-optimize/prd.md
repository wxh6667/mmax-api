# 优化 MiniMax H3 经 New API 对外的视频接口链路

## Goal

优化 mmax-api 作为**能力 API 输出方**的视频链路质量：让 minimax-h3 视频能力经由 New API（openai_video 协议 / Task Plugin 渠道）转出时，任务不因服务重启丢失、计费字段完整、进度可感知、内容可流式播放，并对齐 OpenAI Video 协议的事实标准字段。优化主体是 mmax-api 服务端（`mmax_api/`），New API 侧插件默认不动（仅在服务端字段就绪后可选补 `extractUsageOnComplete`）。

## Background / Evidence

调研结论（详见 `research/`）：

- New API 后台轮询任务时 **404 → 立即判 FAILURE 并退款**；连续 20 次失败同样判死。mmax-api 的 `JobStore` 是纯内存 dict，`update.sh` 发布重启或进程崩溃后所有任务 404——GPU 在跑/已出片，New API 侧却已判死退款，产物取不回。这是链路上最脆弱的一环。
- New API 完成时按响应中实测 `seconds`/`size` 结算计费（sora 模式）；`_public_job` 剔除 payload 后完成响应缺这两个字段，计费只能按提交时估算。
- OpenAI Video 对象含 `prompt`/`seconds`/`size`；mmax 公开 job 对象缺这三个字段（status 枚举已完全一致）。
- H3 进度仅 5→85→92 三档跳变，生成期客户端长期只见 5%。
- New API `VideoProxy` 会向 mmax-api 转发 Range/206 请求（最终用户在线播放/拖进度条依赖）；Starlette `FileResponse` 不处理 Range，现返回 200 全量。

## Requirements

### P0 — 链路正确性（本任务必做）

1. **任务状态持久化**：job 元数据落盘（方案见决策点），服务重启后：
   - 已完成任务仍可 `GET /v1/videos/{id}` 查询、`/content` 取片（产物文件本就在 outputs/ 磁盘上）；
   - 重启时处于 queued/in_progress 的任务标记为 failed（进程确实中断），错误信息明确（如 `service_restarted`），New API 轮询能拿到终态而非 404；
   - 图片任务同样受益（同一 JobStore）。
2. **公开 job 对象补齐协议字段**：`_public_job` 透出 `seconds`、`size`、`prompt`（来自 payload），对齐 OpenAI Video 对象，同时服务 New API 完成时计费结算。

### P1 — 体验与兼容（待确认范围）

3. **H3 进度粒度**：若 DiffSynth 管道支持 step callback，则按推理步数更新 progress（5→95 线性）；不支持则维持现状并记录原因。
4. **content 端点 Range 支持**：`/content` 处理 `Range` 请求返回 206/`Content-Range`（视频与图片共用 helper），支持最终用户经 New API 在线播放与拖动。

### P2 — 卫生工作（待确认范围）

5. **文档重写**：`docs/new-api.md` 去除 Krea 残留，按 HiDream + H3 现状重写（含计费表达式配置示例 `u("seconds")`）；README 相应小节同步。
6. **Krea 死代码清理**：删除 `mmax_api/backends/krea2.py`、`mmax_api/state_dict_converters.py`、`scripts/prepare_krea.py`，同步 `install.sh` 尾部提示、CI compileall 列表、`cleanup_legacy.sh`。

## Constraints

- 保持单 worker 单 GPU FIFO 队列架构不变；不引入数据库服务（持久化用本地文件）。
- 不改变现有对外协议的语义（字段只增不改不删）；`/v1/*` 鉴权方式不变。
- 遵循项目约定：中文注释/日志、`MMAX_*` 环境变量配置、无新 pip 依赖（持久化用标准库 json）。
- 网关兼容逻辑不进核心服务（New API 适配留在 integrations/ 插件层）。

## Acceptance Criteria

- [x] `python -m compileall -q mmax_api` 通过（CI 同款）；`bash -n scripts/*.sh` 通过
- [x] P0-1：JobStore 持久化往返验证通过（本机双实例模拟重启：completed 可查、in_progress → failed(service_restarted)、未知 id → None）
- [x] P0-2：`_public_job` 回显 `seconds`/`size`/`prompt` 验证通过（stub 导入实测 video/image 两类）
- [x] P1-3：H3 去噪进度按步上报已实现（DiffSynth 官方扩展点 `progress_bar_cmd` 注入，5~90 线性）；生成期实测待部署机确认
- [x] P2：`docs/new-api.md` 已重写无 Krea 引用；krea 死代码已删（`grep -ri krea` 仅剩 cleanup_legacy.sh 与其服务器清理路径）
- [ ] 部署机 `update.sh` 发布后 `healthcheck.sh` 通过，README curl 示例可正常生成视频（待服务器操作）

## 实施结果（2026-10-09）

提交 `7eb8fbd`（main）。改动：`mmax_api/jobs.py`（SQLite 写穿透/读回填/启动恢复）、`mmax_api/api.py`（_public_job 补字段）、`mmax_api/backends/h3.py`（_denoise_progress_bar）、删除 krea2.py/state_dict_converters.py/prepare_krea.py、install.sh/migrate_legacy.sh/syntax.yml 同步、docs/new-api.md 重写。

## Decisions（2026-10-09 用户确认）

1. **持久化方案：SQLite**（标准库 sqlite3，库文件在 runtime 目录；不引入数据库服务）。
2. P1 纳入 **H3 进度粒度**；content Range 支持移出本任务（可选后续）。
3. P2 两项全部纳入（重写 new-api 文档 + 清理 Krea 死代码）。

最终范围：P0-1（SQLite 持久化）、P0-2（补协议字段）、P1-3（进度粒度）、P2-5（文档）、P2-6（清理）。

## Notes

- 依赖事实：New API v1.0.0-rc.27+ 的 Task Plugin 体系；OpenAI 官方 Videos API 已于 2026-09-24 关闭，New API 的 openai_video 协议为事实标准。
- 插件侧可选后续（不在本任务）：补 `extractUsageOnComplete` 从完成响应读实测 seconds/size（依赖 P0-2 字段）。
