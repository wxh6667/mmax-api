# Deployment / Install Guidelines

> `scripts/install.sh` 等部署脚本的可执行契约。面向修改部署脚本或新增部署步骤的场景。

---

## Scenario: 数据盘守卫与模型下载

### 1. Scope / Trigger

- 触发：`scripts/install.sh` 涉及外部存储（数据盘）、大文件下载、env wiring 与 pip 缓存，属 infra 类改动。
- 适用：任何修改 `scripts/install.sh`、`.env.example` 中部署相关键，或新增部署脚本。

### 2. Signatures

- 命令：`bash scripts/install.sh`
- 环境键（定义见 `.env.example`）：

| 键 | 默认 | 含义 |
|---|---|---|
| `MMAX_DATA_DIR` | `/root/autodl-tmp` | 数据根目录；必须位于独立挂载的数据盘 |
| `MMAX_ALLOW_NO_DATA_DISK` | 未设 | 设为 `1` 跳过数据盘挂载检查（确知要用系统盘 / 非 AutoDL 环境） |

### 3. Contracts

- **数据盘守卫**：在任何 `mkdir` / venv 创建 / 模型下载之前，检查 `MMAX_DATA_DIR` 是否为独立挂载点
  （优先 `mountpoint -q`，回退 `findmnt`，再回退 `/proc/mounts` 第二列**精确**匹配）。判定依据是
  "是否为挂载点"而非"目录是否存在"——目录可能正是脚本自己 `mkdir` 出来的。
- **模型下载只拉必需文件**：大权重仓库必须用 `allow_patterns` 限定必需文件。H3 NF4 仅需
  `settings.h3_dit/h3_text_encoder/h3_video_vae/h3_audio_vae` 的 basename 这 4 个文件
  （整仓 ≈72.5 GB，必需仅 ≈27.7 GB）。
- **清理类操作尽力而为**：pip 缓存清理失败不得中断已完成的安装，但必须显式告警，不得谎报成功。

### 4. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| `MMAX_DATA_DIR` 非挂载点且未设覆盖开关 | stderr 打印明确错误，`exit 1`（早于 venv/mkdir/下载） |
| `MMAX_ALLOW_NO_DATA_DISK=1` | 跳过检查，继续执行 |
| `MMAX_DATA_DIR` 是挂载点 | 通过检查，继续执行 |
| H3 NF4 4 文件齐全 | 幂等跳过下载 |
| `pip cache purge` 失败 | stderr 告警 `WARNING`，安装继续、不谎报成功 |

### 5. Good / Base / Bad Cases

- **Good**：数据盘已挂载；NF4 只下 4 个文件；安装完成，pip 无残留缓存。
- **Base**：重复运行；模型齐全跳过下载；pip 无缓存时 purge 删除 0 个文件。
- **Bad**：无数据盘时静默 `mkdir /root/autodl-tmp` 落到 30G 系统盘，≈28GB 权重写满系统盘后失败。

### 6. Tests Required

- `bash -n scripts/install.sh` 与 `shellcheck scripts/install.sh` 必须通过。
- 守卫：在无数据盘路径下运行必须 `exit 1`；设 `MMAX_ALLOW_NO_DATA_DISK=1` 必须继续。
- 断言 `allow_patterns` 生成的 pattern 恰好等于上述 4 个必需文件名。

### 7. Wrong vs Correct

#### Wrong

```bash
# 无过滤 → 整仓 ≈72.5GB
snapshot_download("DiffSynth-Studio/MiniMax-H3-NF4", local_dir=str(nf4_dir))

# 无检查 → 数据盘缺失时静默写到系统盘
mkdir -p /root/autodl-tmp/outputs/videos /root/autodl-tmp/models
```

#### Correct

```bash
# 只下必需文件
snapshot_download(
    "DiffSynth-Studio/MiniMax-H3-NF4",
    allow_patterns=[Path(p).name for p in nf4_files],
    local_dir=str(nf4_dir),
)

# 先校验挂载点，未挂载则明确失败
if is_mountpoint "$DATA_DIR"; then ... else echo "ERROR: data disk not mounted" >&2; exit 1; fi
```
