# 修复安装脚本模型下载的磁盘浪费

## Goal

让 `scripts/install.sh` 在受限磁盘上部署时不再浪费空间、也不再静默写满系统盘：

1. 下载 H3 NF4 权重时只拉必需文件，不再整仓下载（省 ≈44.8 GB）；
2. 未挂载数据盘时明确失败，而不是把权重静默写到 30G 系统盘上；
3. 安装后不残留 pip wheel 缓存（省 ≈3.6 GB）。

## Background / Evidence

调研结论（一手体积数据与来源 URL）见
`.trellis/tasks/10-09-h3-newapi-optimize/research/deployment-disk-sizing.md`。要点：

- 仓库 `DiffSynth-Studio/MiniMax-H3-NF4` 整仓 ≈72.5 GB，而 mmax 实际只用 4 个文件共 ≈27.7 GB；
  `install.sh` 当前 `snapshot_download(..., local_dir=...)` 无过滤，会把整仓拉下来。
- `install.sh` 里 `mkdir -p /root/autodl-tmp/...` 在数据盘缺失（`/root/autodl-tmp` 非挂载点）时，
  会在系统盘上静默建同名目录，后续权重全部落到 30G 系统盘。
- pip 安装的 torch/CUDA wheels（≈3.6 GB）默认留在缓存目录，未清理。

## Requirements

### P0

1. **H3 NF4 只下必需文件**：`snapshot_download("DiffSynth-Studio/MiniMax-H3-NF4", ...)` 增加文件过滤，
   仅下载以下 4 个文件：
   - `minimax-h3-fl2va-pruned-nf4.safetensors`
   - `minimax-h3-text-encoder-nf4.safetensors`
   - `video_vae_nf4.safetensors`
   - `audio_vae_nf4.safetensors`

   现有的"文件齐全则跳过"幂等判断保持有效。

2. **数据盘守卫**：在写入数据目录（默认 `/root/autodl-tmp`，可被 `MMAX_DATA_DIR` 覆盖）之前，
   检查该路径是否为独立挂载点。若不是（即数据盘未挂载，写入会落到系统盘）：
   - 以**明确错误**中止，错误信息说明"数据盘未挂载、继续会写入系统盘"；
   - 提供显式覆盖开关（环境变量，例如 `MMAX_ALLOW_NO_DATA_DISK=1`），设置后可继续，
     供确知自己在用系统盘、或非 AutoDL 环境使用。
   - 判定依据是"是否独立挂载"，不是"目录是否存在"——因为目录可能由脚本自己 `mkdir` 出来。

3. **清理 pip 缓存**：安装流程结束后释放 pip wheel 缓存（安装时 `--no-cache-dir` 或安装后 `pip cache purge`），
   避免约 3.6 GB 缓存留在系统盘。

### 约束

- 改动限定在 `scripts/install.sh`（如需同步说明，可少量改 `.env.example` / `README.md`）。
- 不改动模型推理、API、任务队列等运行逻辑。
- 脚本保持幂等、可重复运行；已有 `.env`、`.api_key`、已下模型的复用行为不变。

## Acceptance Criteria

- [ ] 数据盘未挂载且未设置覆盖开关：`install.sh` 在写盘/下载前以明确错误中止，系统盘不产生模型目录。
- [ ] 设置覆盖开关后：可继续执行，行为与旧版一致。
- [ ] `/root/autodl-tmp` 为挂载点时：检查通过，install.sh 正常完成。
- [ ] NF4 下载完成后目标目录内只有上述 4 个 `.safetensors`，无 `fl2va-nf4` / `ref2va-*` 等未用文件，体积 ≈27.7 GB。
- [ ] 重复运行 `install.sh`：模型齐全时仍幂等跳过下载。
- [ ] 安装结束后 pip 缓存无残留 wheel 占用。

## Notes

- 本任务为轻量任务，PRD-only。
- 不在本任务范围：`/autodl-pub` 是否可复用权重、`.venv` 复用 base torch（`--system-site-packages`）、
  outputs 轮转脚本、按剩余空间给出容量提示——均可在后续任务评估。
