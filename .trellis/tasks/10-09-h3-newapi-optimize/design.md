# Design — H3 → New API 视频链路优化

对应 prd.md 已确认范围：SQLite 持久化、补协议字段、H3 进度粒度、文档重写、Krea 清理。

## 1. JobStore SQLite 持久化（P0-1）

**改动文件**：`mmax_api/jobs.py`（保持模块单例 `jobs` 与对外方法签名不变：`create/get/update/finish/fail`）。

**架构：写穿透 + 读回填**
- 内存 dict 仍为运行时第一来源（`get()` 走内存，含 PIL Image 对象，轮询零 DB 开销）；
- 每次状态变更（create/update/finish/fail）在 RLock 内同步 `INSERT OR REPLACE` 整行到 SQLite；
- `get()` 内存 miss 时查 SQLite 并回填内存（重启后查询已完结任务的路径）。

**存储**
- 库文件：`settings.runtime_dir / "jobs.db"`（runtime 目录由 `ensure_runtime_dirs` 保证存在）。
- `sqlite3.connect(path, check_same_thread=False)` 单连接 + 现有 RLock 保护 + `PRAGMA journal_mode=WAL`。单 GPU 串行任务量，无性能压力。
- 表：`jobs(id TEXT PRIMARY KEY, object, model, status, progress, created_at, completed_at, error /*JSON*/, output_path, payload /*JSON*/)`。

**序列化**
- payload 含不可序列化对象（`keyframes`/`edit_images` 为 PIL Image）。持久化用 `json.dumps(job, default=lambda _o: None)` 把 Image 降为 None——恢复场景只依赖标量字段（seconds/size/prompt/status/output_path），Image 无论如何不再可用（未完成任务恢复即判 failed，已完成任务产物在磁盘）。

**启动恢复**（JobStore 构造时执行）
1. `CREATE TABLE IF NOT EXISTS`；
2. `UPDATE jobs SET status='failed', progress=100, completed_at=now, error='{"code":"service_restarted","message":"服务重启，任务已中断。"}' WHERE status IN ('queued','in_progress')`——New API 轮询拿到明确终态而非 404。

**不做的**：不做 TTL/清理（outputs 已有产物文件语义，任务量极低，遗留任务由运维清理）；不迁移历史（首次运行建空表）。

## 2. 公开 job 对象补协议字段（P0-2）

**改动文件**：`mmax_api/api.py` `_public_job`。

- video：从 `job["payload"]` 透出 `seconds`（数值，OpenAI 官方是字符串枚举但 New API usageSchema 用 number，保持数值）、`size`、`prompt`。
- image：透出 `prompt`、`size`（payload 中为 `"WxH"` 字符串；无 seconds）。
- 字段只增不改，`_wait_for_job` 与插件链路不受影响；New API 完成时结算可从响应读实测 seconds/size。

## 3. H3 进度粒度（P1-3）

**前置查证（实现第一步）**：DiffSynth-Studio `MiniMaxH3Pipeline.__call__` 是否支持逐步回调（diffusers 风格 `callback_on_step_end` 或 DiffSynth 自有 callback 参数）。查证途径：modelscope/DiffSynth-Studio 仓库 `diffsynth/pipelines/minimax_h3_audio_video.py`（部署机 `.deps/DiffSynth-Studio` 同源）。

- **支持** → `generate()` 传 callback，按 `(step+1)/total_steps` 线性映射 progress 5→90（90+ 为写盘/ffmpeg 阶段）；callback 在 GPU worker 线程执行，`jobs.update` 有锁线程安全。
- **不支持** → 维持 5/85/92 现状，在任务 notes 记录取证结论，不臆造方案（如 hook tqdm / 时间插值这类不可靠手段不做）。

## 4. Krea 死代码清理（P2-6）

- 删除：`mmax_api/backends/krea2.py`、`mmax_api/state_dict_converters.py`、`scripts/prepare_krea.py`（均无引用，已核实）。
- `scripts/install.sh`：删除末尾 3 行 Krea 提示 echo。
- `.github/workflows/syntax.yml`：compileall 改为 `python -m compileall -q mmax_api`（scripts 下将无 .py）。
- `scripts/cleanup_legacy.sh` 保留（语义是清理服务器旧权重，仍有效）。
- 收尾 `grep -ri krea` 全仓库核对。

## 5. 文档重写（P2-5）

`docs/new-api.md` 全文重写为 HiDream + H3 双渠道现状：
- 拓扑图更新（去 Krea 渠道）；
- H3 Task Plugin 接入步骤保留更新；
- 新增计费节：New API 表达式计费示例（`u("seconds")` 引用 usageSchema facts、提交预留/完成结算机制），说明 mmax-api 完成响应已含实测 seconds/size；
- 图片节按 HiDream 现状（多参考、steps/cfg/shift 覆盖；删除 Krea 的 strength 字段描述）；
- README 交叉核对（无 Krea 残留——已确认 README 干净）。

## 实施顺序

1. 查证 DiffSynth H3 回调支持（定 P1-3 走向）
2. jobs.py SQLite 改造；api.py 补字段
3. H3 进度（视 1）
4. Krea 清理 + install.sh/CI 同步
5. docs/new-api.md 重写
6. 验证：`python -m compileall -q mmax_api`、`bash -n scripts/*.sh`、JobStore 持久化往返脚本（本机可验，无需 GPU）、部署机 update.sh + healthcheck

## 风险

- sqlite3 跨线程：单连接 + check_same_thread=False + 全程 RLock，写入点少，风险可控。
- 恢复的 completed 任务若 outputs 文件被人工删除，`/content` 会 404 on FileResponse——保持现状（运维问题），不在本任务扩大范围。
