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

---

## Common Mistakes / Gotchas

### Gotcha: `df` 看不到 AutoDL 数据盘（bind mount）

- **现象**：`df -h` 里没有 `/root/autodl-tmp` 这一行（只有 `/dev/md0` 挂在 `/init`），据此会误判"数据盘未挂载"。
- **原因**：AutoDL 容器里数据盘以 **bind mount** 形式挂载，`df` 默认不列出 bind mount。
- **正确判据**：用 `findmnt /root/autodl-tmp` 或 `mountpoint /root/autodl-tmp` 判断。
  `mountpoint -q` 也正是 `install.sh` 守卫采用的判据，能正确识别已挂载的数据盘。**不要只看 `df`**。

### Gotcha: 无卡模式没有 GPU，且 CPU/内存极低

- 无卡模式（面板 `GPU: No devices were found`，常见 0.5 核 / 2GB）可 clone 代码、装环境、下模型，
  但**跑不了 H3 / HiDream 推理**；且 0.5 核 2GB 下 `pip install` torch+CUDA（≈3.6GB wheel）会很慢甚至 OOM。
- 结论：**安装与推理都在 GPU 模式下进行**。

---

## Scenario: 依赖安装（diffsynth extra / 版本约束 / 冒烟校验）

### 1. Scope / Trigger

- 触发：修改 `scripts/install.sh` 的依赖安装段，或调整 diffsynth / torch / transformers 的安装方式。
- 适用：任何可能导致"服务能起、但模型后端跑不了"的依赖改动。

### 2. Signatures

- 命令：`bash scripts/install.sh`
- 环境键（定义见 `.env.example`）：

| 键 | 默认 | 含义 |
|---|---|---|
| `MMAX_VENV_SYSTEM_SITE` | `1` | venv 用 `--system-site-packages` 复用镜像 torch；`0` 用隔离 venv（会重下 torch ≈3.6GB） |
| `MMAX_DIFFSYNTH_EXTRAS` | `audio` | 安装 diffsynth 时附加的 extras |
| `MMAX_DIFFSYNTH_CONSTRAINTS` | `transformers<5` | 追加版本约束；**值必须加引号**（见 Gotcha） |
| `MMAX_PIP_NO_CACHE` | 未设 | 设 `1` 恢复 `--no-cache-dir` |

### 3. Contracts

- **必须带 `[audio]` extra**：`mmax_api/backends/h3.py` 在 import 阶段即触发
  `diffsynth.utils.data.audio`（顶层 `import torchaudio`）与 `diffsynth.utils.data.audio_video`（顶层 `import av`），
  二者属 diffsynth 的 `[audio]` extra、**默认不装**。两条安装路径（本地 clone 的 `-e`、PyPI 回退）都必须带上。
- **必须约束版本**：diffsynth 对 `torch`/`transformers`/`torchvision` 几无上界。复用镜像 torch 时自动追加
  `torch==<探测到的镜像版本>`，防止 pip 解析最新 torchvision 时连带升级 torch；用户已自钉 torch 则跳过并提示。
- **冒烟校验放在模型下载之前**：依赖装完即 import
  `torch/torchvision/torchaudio/av/transformers/fastapi/uvicorn` 与 `MiniMaxH3Pipeline`，失败 `exit 1`。
  放在 ≈28GB 模型下载之前，避免下完才发现依赖坏。
- **pip 缓存：安装期保留、最后 purge**：慢链路上保留缓存使失败重试只需补差量；`pip cache purge` 放最后一步，
  只在冒烟校验通过后执行。

### 4. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| `MMAX_VENV_SYSTEM_SITE=0` | stderr 告警"将自行下载完整 torch" |
| 复用镜像 torch 且用户未钉 torch | 自动加 `torch==<镜像版本>` |
| 用户已在 `MMAX_DIFFSYNTH_CONSTRAINTS` 钉了 torch | 不追加，打印提示（避免两个冲突的 torch 规格） |
| 已有 `.venv` 且 system-site 属性不符 | 打印 `WARNING` + 提示重建，**不擅自删除** venv |
| 冒烟校验任一 import 失败 | stderr 明确错误 + `exit 1`；不打印 `INSTALL DONE`、不执行 purge |
| `pip cache purge` 失败 | `WARNING`，不中断 |

### 5. Good / Base / Bad Cases

- **Good**：复用镜像 torch → 带 `[audio]` + 约束 → 冒烟通过 → 下模型 → 最后 purge → `INSTALL DONE`。
- **Base**：重复运行；依赖齐备，pip 无事可做；校验通过。
- **Bad**：裸装 `diffsynth`（无 `[audio]`）→ 服务能起、`/health` 正常，但第一条 H3 请求
  `ModuleNotFoundError: No module named 'torchaudio'`。

### 6. Tests Required

- `bash -n scripts/install.sh` 与 `shellcheck scripts/install.sh` 必须通过。
- `grep -c -- "--no-cache-dir" scripts/install.sh` 必须为 `1`（只在 `PIP_CACHE_FLAG` 定义处）。
- 断言 `[audio]` 同时出现在 clone 路径与 PyPI 回退路径。
- 断言 冒烟校验行号 < 模型下载行号 < `pip cache purge` 行号。
- 冒烟校验失败时脚本必须非零退出、不打印 `INSTALL DONE`、不执行 purge。

### 7. Wrong vs Correct

#### Wrong

```bash
# 裸装：H3 顶层 import torchaudio / av 直接失败
"$PYTHON_BIN" -m pip install -e "$DIFFSYNTH_PATH"
"$PYTHON_BIN" -m pip install diffsynth
```

#### Correct

```bash
"$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG -e "${DIFFSYNTH_PATH}[${DIFFSYNTH_EXTRAS}]" $DIFFSYNTH_CONSTRAINTS
"$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG "diffsynth[${DIFFSYNTH_EXTRAS}]" $DIFFSYNTH_CONSTRAINTS
```

---

## Common Mistakes / Gotchas（依赖安装）

### Gotcha: `.env` 会被 `source`，值里的 `<` `>` 必须加引号

- **现象**：`.env` 写 `MMAX_DIFFSYNTH_CONSTRAINTS=transformers<5`，`install.sh` source 后变量变成 `transformers`，
  `<5` 被当成输入重定向；上界被静默丢掉，`set -e` 下还可能直接中止。
- **原因**：`install.sh` 用 `set -a; source .env` 加载配置，未加引号的值会被 bash 当作 shell 语法解析。
- **正确**：`MMAX_DIFFSYNTH_CONSTRAINTS='transformers<5'`（凡含 shell 元字符的值一律加引号）。

### Gotcha: `[[ =~ ]]` 里的正则不能含裸 `<` `>`

- **现象**：`[[ "$s" =~ [=<>!~] ]]` 使整个脚本 `bash -n` 报 `syntax error near ...`。
- **原因**：`[[ ]]` 内 `<`/`>` 是重定向/比较运算符，bash 解析器不理解正则字符类。
- **正确**：把正则放进变量再引用：`RE='[=<>!~]'; [[ "$s" =~ $RE ]]`。
