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
- **必须钉住整个 torch 家族，不只是 `torch`**：diffsynth 对 `torch`/`transformers`/`torchvision` 几无上界，
  而 `[audio]` extra 里的 `torchaudio` / `torchcodec` **连"受 torch 约束"都谈不上**——实测
  `torchaudio 2.11.0` 的 `requires` 是**空的**（它把 torch 钉版删了），`torchcodec` 任何版本都**不声明**
  torch 依赖。只钉 `torch` 会让二者漂到为其配套的更高 torch / CUDA 编译的版本，import 时
  `OSError: libcudart.so.13: cannot open shared object file`（已在 AutoDL 容器上确定性复现）。
  复用镜像 torch 时必须同时追加 `torch==<base> torchaudio==<base> torchcodec==<按兼容表查到的次版本>`；
  用户已自钉 torch 则跳过并提示（避免两个冲突的 torch 规格）。
- **torchcodec 版本查表，不猜**：torchcodec 与 torch 的配套关系**没有依赖声明可依**（见上），只能按官方
  兼容表 `https://github.com/pytorch/torchcodec#installing-torchcodec` 映射（脚本内 `torchcodec_for()`：
  2.7→0.5 / 2.8→0.7 / 2.9→0.9 / 2.10→0.10 / 2.11→0.11）。表里没有该 torch 次版本时**保持 torchcodec
  不钉**并打 `WARNING` 提示补表，而不是静默放行一个可能 ABI 不匹配的版本。
- **冒烟校验必须覆盖"非 import 型"与"懒加载"两类盲点**：依赖装完即 import
  `torch/torchvision/torchaudio/torchcodec/av/transformers/fastapi/uvicorn` 与 `MiniMaxH3Pipeline`。
  额外两项不可省：
  - **显式** `from torchcodec.decoders import AudioDecoder` / `from torchcodec.encoders import AudioEncoder`
    ——diffsynth 对 torchcodec 是**函数内懒加载**，只 import `MiniMaxH3Pipeline` 永远触发不到它。
    注意区分两件事：上一版校验的 import 列表**已含 `torchaudio`**，所以它**抓住了** `libcudart.so.13`
    （fail-fast 正常生效）；上一版的真正盲点只有 torchcodec 这一个。
  - `command -v ffmpeg` 检查二进制存在——mmax 的 H3 后处理用 `subprocess.run(["ffmpeg", …])` 直接调用它，
    ffmpeg **不在任何 Python import 路径上**，import 校验抓不到。
  失败一律 `exit 1`。整段校验刻意放在 ≈28GB 模型下载**之前**，避免下完才发现依赖坏。
- **pip 缓存：安装期保留、最后 purge**：慢链路上保留缓存使失败重试只需补差量；`pip cache purge` 放最后一步，
  只在冒烟校验通过后执行。

### 4. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| `MMAX_VENV_SYSTEM_SITE=0` | stderr 告警"将自行下载完整 torch" |
| 复用镜像 torch 且用户未钉 torch | 追加 `torch==<base> torchaudio==<base> torchcodec==<表查值>` |
| torch 次版本不在 torchcodec 兼容表 | 打 3 行 `WARNING`；torchcodec **保持不钉**，torch/torchaudio 照钉 |
| 用户已在 `MMAX_DIFFSYNTH_CONSTRAINTS` 钉了 torch | 不追加，打印提示（避免两个冲突的 torch 规格） |
| 已有 `.venv` 且 system-site 属性不符 | 打印 `WARNING` + 提示重建，**不擅自删除** venv |
| ffmpeg 二进制不在 `PATH` | stderr 明确错误 + `exit 1`（早于模型下载） |
| 冒烟校验任一 import 失败 | stderr 明确错误 + `exit 1`；不打印 `INSTALL DONE`、不执行 purge |
| `pip cache purge` 失败 | `WARNING`，不中断 |

### 5. Good / Base / Bad Cases

- **Good**：复用镜像 torch → 带 `[audio]` + 钉全家族（含 torchcodec 查表）→ 冒烟（含 ffmpeg 二进制与
  torchcodec 显式 import）通过 → 下模型 → 最后 purge → `INSTALL DONE`。
- **Base**：重复运行；依赖齐备，pip 无事可做；校验通过。
- **Bad**：裸装 `diffsynth`（无 `[audio]`）→ 服务能起、`/health` 正常，但第一条 H3 请求
  `ModuleNotFoundError: No module named 'torchaudio'`。
- **Bad**：带 `[audio]` 但**只钉 `torch`** → torchaudio 漂到 `2.11.0`（为 CUDA 13 编译），
  import 报 `OSError: libcudart.so.13`，服务连起都起不来。

### 6. Tests Required

- `bash -n scripts/install.sh` 与 `shellcheck scripts/install.sh` 必须通过。
- `grep -c -- "--no-cache-dir" scripts/install.sh` 必须为 `1`（只在 `PIP_CACHE_FLAG` 定义处）。
- 断言 `[audio]` 同时出现在 clone 路径与 PyPI 回退路径。
- 断言 `torchcodec_for 2.8` 输出 `0.7`，未知次版本输出空（据此走 WARNING 分支）。
- 断言 依赖安装 → 冒烟校验（含 ffmpeg 检查）的行号 < 模型下载行号 < `pip cache purge` 行号。
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
# 只钉 torch：torchaudio / torchcodec 仍漂到为更高 torch/CUDA 编译的版本
DIFFSYNTH_CONSTRAINTS="$DIFFSYNTH_CONSTRAINTS torch==$base_torch"
"$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG "diffsynth[${DIFFSYNTH_EXTRAS}]" $DIFFSYNTH_CONSTRAINTS
```

#### Correct

```bash
# 钉全家族；torchcodec 按官方兼容表查（2.8 -> 0.7），查不到则告警不钉
torchcodec_ver="$(torchcodec_for "${base_torch%.*}")"
DIFFSYNTH_CONSTRAINTS="$DIFFSYNTH_CONSTRAINTS torch==$base_torch torchaudio==$base_torch"
[[ -n "$torchcodec_ver" ]] && DIFFSYNTH_CONSTRAINTS="$DIFFSYNTH_CONSTRAINTS torchcodec==$torchcodec_ver"
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

### Gotcha: `torchaudio` / `torchcodec` 不受 `torch` 的版本约束保护

- **现象**：脚本已追加 `torch==2.8.0`，pip 仍装上 `torchaudio-2.11.0` + `torchcodec-0.17.0`，
  冒烟校验报 `OSError: libcudart.so.13: cannot open shared object file`。
- **原因**：查 PyPI 元数据可知，`torchaudio 2.11.0` 的 `requires` 是**空列表**（它把 torch 钉版删了），
  `torchcodec` 任何版本都**不声明** torch 依赖。pip 因而自由选最新版，装到为 torch 2.11 / CUDA 13
  编译的二进制，与镜像的 `torch 2.8.0+cu128` ABI 不匹配。
- **正确**：`torchaudio` 钉成与 `torch` 同版本，`torchcodec` 按官方兼容表查（见 §3）。
  **不要**以为"钉了 torch 就安全了"——版本约束是逐包声明的，家族里每个成员都要单独确认。
- **验证过的现象**：`pin torchaudio==2.8.0` 时 pip 实际装的是 `2.8.0+cu128`（PEP 440 local
  version 满足 `==2.8.0`），即"同版本"不代表"无 local tag"，比对版本号时要去掉 `+` 后缀。

### Gotcha: 冒烟校验会被"懒加载"与"非 import 型依赖"同时绕过

- **现象**：冒烟校验 import `MiniMaxH3Pipeline` 全过，torchcodec 的 ABI 错误却漏到运行时。
- **原因**：diffsynth 在**函数内部**才 `from torchcodec.decoders import AudioDecoder`，import 管线触发
  不到它；同理 `ffmpeg` 是 `subprocess.run` 调用的**外部二进制**，不在任何 Python import 路径上。
- **正确**：冒烟校验要显式 import torchcodec 的具体符号（`AudioDecoder` / `AudioEncoder`），
  并用 `command -v ffmpeg` 单独查二进制。判据是"mmax 实际用到什么"，而非"能 import 什么"。

### Gotcha: "DiffSynth 是否可用"不能用 clone 目录是否存在来判断

- **现象**：`install.sh` 报 `INSTALL DONE`，紧接着 `bash scripts/restart.sh` 却打印
  "找不到 DiffSynth：/root/autodl-tmp/mmax/.deps/DiffSynth-Studio，请先执行 bash scripts/install.sh"，
  服务起不来 —— 即 prd 禁止的"装上了但跑不了"。
- **原因**：`start.sh` 原用 `[[ -d "$DIFFSYNTH_PATH/diffsynth" ]]` 判断可用性。该目录只在 GitHub
  clone 成功时存在；GitHub 不可达、`install.sh` 回退到 PyPI 包时，diffsynth 在 venv 的
  site-packages 里，这个目录**本就不该存在**。而 AutoDL 上 GitHub 常态不可达，故该误判是常态。
- **正确**：判据用 `"$PYTHON_BIN" -c "import diffsynth"`——要判断的是"依赖是否可用"，而非
  "某个目录是否存在"；后者只是前者的一种（既非充分也非必要）实现。
- **注意别"统一"错**：`install.sh` 里同样的 `[[ -d "$DIFFSYNTH_PATH/diffsynth" ]]` 是**正确**的——
  那里问的是"源码是否已在本地"，据此选择 `-e` 还是 PyPI 安装路径。**同一个判据在语义不同处不可照搬**，
  先问清"要判断的是可用性还是来源"。

---

## Scenario: 在 AutoDL 容器上拉取代码（GitHub 直连与学术加速均不可用）

### 1. Scope / Trigger

- 触发：需要在 AutoDL 容器内 `git clone` / `git pull` 本仓库或其它 GitHub 仓库。
- 适用：任何依赖 GitHub 的部署步骤（`install.sh` 克隆 DiffSynth-Studio、更新脚本、人工拉取）。

### 2. Signatures

- 诊断：

  ```bash
  unset http_proxy https_proxy; git ls-remote origin main   # 直连
  source /etc/network_turbo;    git ls-remote origin main   # 走学术加速
  cat /etc/network_turbo; env | grep -i proxy               # 看代理形态
  ```

- 可用替代路径（公开仓库只读拉取，无需凭证）：

  ```bash
  git remote add mirror https://<mirror-domain>/https://github.com/<owner>/<repo>.git
  git fetch mirror && git merge --ff-only mirror/main
  git remote remove mirror
  ```

### 3. Contracts

- **AutoDL 学术加速（`/etc/network_turbo`）的边界**：仅代理 `github.com`、`githubusercontent.com`、
  `githubassets.com`、`huggingface.co` 四个域名；通过 `http_proxy`/`https_proxy` 生效，代理地址是
  集群内网 RFC1918 地址（实测 `http://172.20.0.113:12798`），**用户无法调参或换上游**。官方明确声明
  "不承诺稳定性保证"，且"若遇恶意攻击等情况将随时停止该加速服务"。**不得把它当作稳定通道依赖。**
- **`no_proxy` 已含魔搭域**（`modelscope.com`/`aliyuncs.com`/`tencentyun.com`/`wisemodel.cn`），
  故模型权重下载本就绕过代理直连，与 `install.sh` 中 `accel_off` 后再下载的设计一致。
- **镜像只读、用完即删**：镜像路线仅用于公开仓库的只读拉取。**不得**用
  `git config --global url.<mirror>.insteadOf` 全局重写——那会把 `push` 也劫持到第三方 CDN。
  `origin` 必须保持指向 `github.com`，镜像只作临时取数通道。
- **本仓库为 public**：读取不需要任何 token/key，因而镜像路线无凭证泄露之虞。

### 4. Validation & Error Matrix

| 路径 | 现象 | 含义 |
|---|---|---|
| 直连 `github.com` | `GnuTLS recv error (-110): The TLS connection was non-properly terminated` | TLS 握手被中途掐断，连接未建立 |
| 走 `/etc/network_turbo` | `The requested URL returned error: 503` | 连接已建立，代理上游回"服务不可用" |
| 走代理 + `http.version=HTTP/1.1` | 仍 503 | 与 HTTP/2 无关，问题在代理上游 |
| `ssh -T -p 443 git@ssh.github.com` | `Permission denied (publickey)` | **连接是通的**（见 Gotcha）；仅缺 GitHub 上登记的公钥 |
| 镜像 `git fetch mirror` | 成功 fast-forward | 走另一条 CDN 路径，绕开上述两个堵点 |

### 5. Good / Base / Bad Cases

- **Good**：`unset` 代理 → 镜像 `fetch` → `merge --ff-only` → `remote remove`；代码到位，`origin` 未被污染。
- **Base**：GitHub 恰好可达时直接 `git pull --ff-only origin main`，无需镜像。
- **Bad**：把学术加速当稳定通道反复重试且无兜底；或配 `insteadOf` 全局重写把 push 也送进第三方 CDN。

### 6. Tests Required

- 拉取后断言 `git log --oneline -1` 的 HEAD 与目标提交一致，且 `git remote -v` 只剩 `origin`。
- 断言 `git status` 无意外本地修改（`--ff-only` 应保证 fast-forward）。

### 7. Wrong vs Correct

#### Wrong

```bash
# 反复重试一个官方声明"不承诺稳定"的代理，且没有兜底路径
source /etc/network_turbo
for i in $(seq 1 8); do git pull --ff-only origin main; sleep 15; done

# 把镜像配成全局重写：push 也会走第三方 CDN
git config --global url."https://ghproxy.net/https://github.com/".insteadOf "https://github.com/"
```

#### Correct

```bash
unset http_proxy https_proxy                    # 镜像走直连，别让学术代理插手
git remote add mirror https://ghfast.top/https://github.com/wxh6667/mmax-api.git
git fetch mirror && git merge --ff-only mirror/main
git remote remove mirror                        # 用完即删：镜像域名寿命短
```

### Gotcha: `ssh -T` 的 `Permission denied (publickey)` 常被误读为"网络不通"

- **现象**：`ssh -T -p 443 git@ssh.github.com` 回 `Permission denied (publickey)`，据此判断 SSH over 443 走不通。
- **误判点**：该报错**恰恰证明连接是通的**——`Warning: Permanently added '[ssh.github.com]:443' ...
  to the list of known hosts` 说明 SSH 握手已完成、主机密钥已交换，卡住的是认证而非网络。
- **正确解读**：`Permission denied (publickey)` = 服务器认不出你的身份，即容器里没有已登记到 GitHub 的公钥。
  GitHub **不允许匿名 SSH**，故走 SSH 必须有 key；而**公开仓库走 HTTPS 匿名即可读**，通常无需折腾 SSH。

### Gotcha: 镜像域名寿命短，且"怕泄露"不该套用到公开仓库上

- **事实**：`wxh6667/mmax-api` 的 `visibility=public`（匿名请求 `api.github.com` 返回 200）。
- **推论**：拉取代码无需任何凭证；镜像路线因而是匿名只读，不存在凭证泄露风险。**不要**因为把私有仓库的
  顾虑错套到公开仓库上而放弃镜像路线。
- **注意**：镜像域名会失效，需现查现用——AutoDL 官方文档给出的 GitHub 跳转页是 `ghproxy.link`
  （HuggingFace 对应 `hf-mirror.com`），页面上列出当前可用域名。实测可用：`ghproxy.net`、`gh-proxy.com`、
  `ghfast.top`、`gh.llkk.cc`。
