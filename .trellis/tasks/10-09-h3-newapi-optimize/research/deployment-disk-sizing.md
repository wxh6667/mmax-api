# mmax-api 在 AutoDL 上的真实磁盘占用与最小容量结论

调研日期：2026-10-10。所有体积均来自一手来源（ModelScope / HuggingFace 仓库 API、官方仓库源码、AutoDL 官方文档、PyPI）。
体积同时给 GiB（`df`/`du` 口径，1024³）与 GB（十进制，1000³），避免口径歧义。

## 0. 结论先行

- **本方案在「30G 系统盘 + 无数据盘」的实例上跑不起来。** 仅 H3 的 4 个 NF4 权重就要 **25.8 GiB（27.7 GB）**，再加 torch/CUDA 运行环境（约 6–9 GiB）就超过 30 GB。必须挂数据盘。
- **仅 H3**：数据盘 **≥ 50 GB** 合理（AutoDL 免费数据盘默认就是 50 GB）；理论下限约 35 GiB，但没有 outputs 余量。
- **H3 + HiDream**：数据盘 **≥ 100 GB** 合理；理论下限约 66 GiB。
- **再加 outputs**：在上一档基础上按日增量预留（见 §5）。
- **系统盘（30 GB）**：至少保留 **≥ 5 GB 可用余量**；`.venv`、`.deps`、模型权重、outputs **都不能放在系统盘**。在无数据盘实例上，`/root/autodl-tmp` 并不存在，install.sh/README 里所有 `/root/autodl-tmp/...` 路径都会落到 30 GB 系统盘上——这是当前部署脚本与本目标机不匹配的根因。
- **最大的一处浪费**：`install.sh` 下载 H3 NF4 时没有加 `allow_patterns`，会整仓拉 **72.5 GB**，而实际只需要 4 个文件共 **27.7 GB**。**加一行参数即可省 44.8 GB**（见 §4 优化 #1）。

## 1. 体积表（条目 → 大小 → 来源）

### 1.1 H3 NF4 权重（mmax 实际使用 4 个文件）

仓库 `DiffSynth-Studio/MiniMax-H3-NF4`，来源：
HuggingFace API `https://huggingface.co/api/models/DiffSynth-Studio/MiniMax-H3-NF4?blobs=true`；
ModelScope API `https://modelscope.cn/api/v1/models/DiffSynth-Studio/MiniMax-H3-NF4/repo/files?Revision=master&Root=`。
两处字节数完全一致。

| 文件 | 字节 | GiB | GB | mmax 是否需要 |
|---|---:|---:|---:|:--:|
| minimax-h3-fl2va-pruned-nf4.safetensors | 10,483,868,433 | 9.76 | 10.48 | ✅ `MMAX_H3_DIT` |
| minimax-h3-text-encoder-nf4.safetensors | 15,324,775,807 | 14.27 | 15.32 | ✅ `MMAX_H3_TEXT_ENCODER` |
| video_vae_nf4.safetensors | 1,613,201,536 | 1.50 | 1.61 | ✅ `MMAX_H3_VIDEO_VAE` |
| audio_vae_nf4.safetensors | 284,004,112 | 0.26 | 0.28 | ✅ `MMAX_H3_AUDIO_VAE` |
| **4 文件合计** | **27,705,849,888** | **25.80** | **27.71** | |
| minimax-h3-fl2va-nf4.safetensors（未剪枝，不用） | 17,162,138,303 | 15.98 | 17.16 | ❌ |
| minimax-h3-ref2va-nf4.safetensors（不用） | 17,162,138,284 | 15.98 | 17.16 | ❌ |
| minimax-h3-ref2va-pruned-nf4.safetensors（不用） | 10,483,868,417 | 9.76 | 10.48 | ❌ |
| README / .gitattributes | ~54 KB | — | — | ❌ |
| **整仓合计（HF usedStorage）** | **72,513,994,892** | **67.53** | **72.51** | 现 install.sh 会全下 |

**4 个文件是否都必须？是。** DiffSynth 官方示例 `MiniMax-H3-NF4-Pruned-FL2VA.py` 的 `model_configs` 正是这 4 个（外加 processor），
来源 `https://github.com/modelscope/DiffSynth-Studio/blob/main/examples/minimax_h3/model_inference_low_vram/MiniMax-H3-NF4-Pruned-FL2VA.py`。

### 1.2 H3 processor 子集

仓库 `MiniMax/MiniMax-H3`（HF 镜像 `MiniMaxAI/MiniMax-H3`）。整仓 HF `usedStorage = 354,028,035,951 B = 329.7 GiB（354.0 GB）`，
但 mmax 只用 `FL2VA/processor/*`（install.sh 已用 `allow_patterns=["FL2VA/processor/*"]`，正确）。
来源 `https://huggingface.co/MiniMaxAI/MiniMax-H3`、`https://modelscope.cn/models/MiniMax/MiniMax-H3`。

| FL2VA/processor/ 下文件 | 字节 |
|---|---:|
| tokenizer.json | 7,032,403 |
| vocab.json | 2,776,833 |
| merges.txt | 1,671,839 |
| chat_template.json | 5,499 |
| tokenizer_config.json | 11,003 |
| preprocessor_config.json | 390 |
| video_preprocessor_config.json | 385 |
| **合计** | **11,498,352 ≈ 11.0 MiB（0.011 GiB）** |

### 1.3 HiDream-O1-Image Full

仓库 `HiDream-ai/HiDream-O1-Image`（DiffSynth 官方示例引用的 model_id）。
来源 `https://huggingface.co/HiDream-ai/HiDream-O1-Image`（API `?blobs=true`）。
`usedStorage = 35,236,791,420 B = 32.82 GiB（35.24 GB）`。

| 文件 | 字节 | GiB |
|---|---:|---:|
| model-00001-of-00008.safetensors | 4,962,686,568 | 4.62 |
| model-00002-of-00008.safetensors | 4,832,049,608 | 4.50 |
| model-00003-of-00008.safetensors | 4,832,049,624 | 4.50 |
| model-00004-of-00008.safetensors | 4,999,856,656 | 4.66 |
| model-00005-of-00008.safetensors | 4,832,049,680 | 4.50 |
| model-00006-of-00008.safetensors | 4,832,049,672 | 4.50 |
| model-00007-of-00008.safetensors | 3,439,582,192 | 3.20 |
| model-00008-of-00008.safetensors | 2,489,319,552 | 2.32 |
| **8 shard 合计** | **35,219,643,552** | **32.80** |
| processor/config/tokenizer（*.json, merges, vocab） | ~12 MB | 0.01 |
| assets/（官方示例图 webp/jpg，推理不需要） | ~15 MB | 0.01 |

README 里 `/root/autodl-tmp/models/hidream-o1-image` 需要 `model-*.safetensors` + processor/config，即 **≈ 32.8 GiB（35.2 GB）**。
（`HiDream-ai/HiDream-O1-Image-Dev` 蒸馏版体积与 Full 相同，也是 32.8 GiB，不能省盘。）

### 1.4 安装占用（torch + CUDA + 依赖）

来源：PyPI `https://pypi.org/pypi/torch/json`、`torchvision`、`nvidia-*-cu12`；DiffSynth `pyproject.toml`
`https://github.com/modelscope/DiffSynth-Studio/blob/main/pyproject.toml`。

DiffSynth 依赖：`torch>=2.0.0, torchvision, transformers, imageio[ffmpeg], safetensors, einops, modelscope, ftfy, pandas, accelerate, peft`。

| 项 | 大小 | 说明 |
|---|---:|---|
| torch wheel（cp310 x86_64，2.14.1） | 528.9 MiB | PyPI 实测 |
| nvidia CUDA 运行时 wheels（cudnn/cublas/cusolver/cusparse/nccl/nvshmem/cufft/... 合计） | ≈ 2.89 GiB | 逐包实测求和（cu12 口径；最新 torch 已切 cu13，量级相同） |
| triton wheel | 236.6 MiB | |
| torchvision wheel | 7.1 MiB | |
| **pip 下载 wheel 合计** | **≈ 3.6 GiB** | 会进入 pip 缓存（可 `--no-cache-dir` 免掉） |
| **`.venv` 安装后占用（估算）** | **≈ 6–9 GiB** | 解包后膨胀 + transformers/peft/accelerate/pandas/modelscope 等（此行为估算，非实测） |
| `.deps/DiffSynth-Studio`（浅克隆源码） | ≈ 20 MiB | GitHub 仓库 size 19990 KB |

**关键点（AutoDL 特有）**：AutoDL 所有内置镜像都装了 Miniconda（`/root/miniconda3/`，在**系统盘**上），
PyTorch 镜像的 torch 也在该 base 环境里；而 `install.sh` 用 `python3 -m venv .venv`（默认 **不带 `--system-site-packages`**）建了隔离环境，
会把 torch + 整套 CUDA wheels **重新装一份**，与 base 镜像里的 torch 形成重复占用。
来源 `https://www.autodl.com/docs/miniconda/`、`https://www.autodl.com/docs/env/`。

### 1.5 单个产出体积（量级）

- **H3 视频**：输出 720p/1792x1024 等，24fps，`libx264 -crf 18 -preset medium -pix_fmt yuv420p` + `aac 192k`（见 `mmax_api/backends/h3.py:169-185`）。
  官方 MiniMax-H3 演示 mp4（`https://huggingface.co/MiniMaxAI/MiniMax-H3` assets/）：`t2va.mp4` 1.56 MiB、`i2va.mp4` 1.02 MiB、`h3_direct_768p.mp4` 2.27 MiB、`t2va_2k.mp4` 5.72 MiB、`h3_direct_2k.mp4` 8.53 MiB。
  据此估算：**720p 4 秒 ≈ 1–3 MB，15 秒 ≈ 5–10 MB**（含音轨约 24 KB/s）。属估算，非实测。
  中间产物 `.raw.mp4` 在 ffmpeg 转码后即删除（`h3.py:187-188`），不会长期双份；但转码瞬间 `.raw.mp4` 与 `.mp4` 并存，峰值约 2×单文件。
- **HiDream 图片**：保存为 **PNG**（`hidream.py:120-121`），最大 2048x2048（约 4MP，`MMAX_HIDREAM_MAX_PIXELS`）。
  PNG 无损：**1536×1536 ≈ 2–4 MB，2048×2048 ≈ 3–8 MB**（内容相关，估算）。改 JPEG/WebP 可降到约 0.3–1 MB。

## 2. 目标机磁盘事实（AutoDL 官方文档）

| 事实 | 数值 | 来源 |
|---|---|---|
| 系统盘（系统盘，本地盘） | **30 GB**，Python 依赖装在系统盘 | `https://www.autodl.com/docs/env/` |
| 数据盘 `/root/autodl-tmp` | 免费 **50 GB 起，可扩容** | `https://www.autodl.com/docs/local_disk/` |
| 容器实例 Pro | **只有 30G 系统盘，无数据盘**；系统盘最大可扩到 500GB | `https://www.autodl.com/docs/instance_pro_data/` |
| Miniconda | 所有镜像都装，路径 `/root/miniconda3/`（系统盘） | `https://www.autodl.com/docs/miniconda/` |
| 文件存储 `/root/autodl-fs` | 免费 20 GB，超出计费 | `https://www.autodl.com/docs/env/` |
| `/root/autodl-pub` | 被列为「不占系统盘」的数据侧目录；**文档未给容量，也未说只读** | `https://www.autodl.com/docs/qa1/` |

**本任务目标机（30G 系统盘、无数据盘、`/root/autodl-tmp` 不存在）对应的是「容器实例 Pro」形态**（`instance_pro_data` 明确写「Pro 暂时无数据盘」）。
因此 install.sh/README 里所有 `/root/autodl-tmp/...` 落盘路径在本机都会落到 30 GB 系统盘上。

## 3. 场景容量结论

用 GiB 口径（`df` 显示口径）。权重为实测，`.venv` 为估算。

**① 仅 H3**
```
H3 NF4 4 文件            25.8 GiB
H3 processor            0.01 GiB
.venv（torch+CUDA+依赖） 6–9 GiB
.deps/DiffSynth 源码    0.02 GiB
--------------------------------------
合计                     ≈ 32–35 GiB
```
→ 数据盘 **≥ 50 GB 合理**（AutoDL 免费默认值，留 ~15 GB outputs 余量）。下限约 35 GiB 可跑但无余量。

**② H3 + HiDream**
```
①                        ≈ 32–35 GiB
HiDream Full             +32.8 GiB
--------------------------------------
合计                     ≈ 65–68 GiB
```
→ 数据盘 **≥ 100 GB 合理**。50 GB 不够。

**③ 再加 N 天 outputs 预留**
按小规模服务估：20 视频/天 × ~5 MB + 200 图/天 × ~4 MB ≈ **~1 GB/天**（估算）。
- 30 天 ≈ 30 GB → 在 ② 基础上数据盘 **≥ 130 GB**；
- 或做 outputs 轮转（见 §4 #6），把预留压到 10–20 GB，数据盘回到 100 GB。

**系统盘（30 GB）余量**：至少保留 **≥ 5 GB 可用**。做法：venv/权重/outputs 全部放数据盘；清理 `/root/miniconda3/pkgs/`、`/tmp`、`/root/.cache`、`~/.cache/modelscope`、回收站（AutoDL 文档 `qa1` 给出的正是这些位置）。

## 4. 优化清单（按「省空间 / 难度 / 风险」排序）

| # | 手段 | 省多少 | 难度 | 风险 | 说明 / 证据 |
|---|---|---|---|---|---|
| 1 | **H3 NF4 下载加 `allow_patterns`** | **≈ 44.8 GB** | 极低 | 低 | 现 `snapshot_download(".../MiniMax-H3-NF4", local_dir=...)` 无过滤 → 整仓 72.5 GB。改成只下 4 个文件 → 27.7 GB。`snapshot_download` 支持 `allow_patterns`/`ignore_patterns`（modelscope 源码 `snapshot_download.py`）。DiffSynth 官方示例也是按文件 pattern 下载。 |
| 2 | **不需要就关掉 HiDream** | 32.8 GiB | 极低 | 无（功能取舍） | `MMAX_HIDREAM_ENABLED=false` 且不下载。 |
| 3 | **pip `--no-cache-dir` + `pip cache purge`** | ≈ 3–4 GiB | 极低 | 无 | pip 下载的 torch/CUDA wheels（≈3.6 GiB）默认进缓存。安装后 `pip cache purge` 即可释放。 |
| 4 | **venv/权重/outputs 放数据盘** | 决定成败 | 低 | 无 | `.env.example` 已用 `MMAX_*` 覆盖；把 `MMAX_PYTHON_BIN`/`MMAX_DIFFSYNTH_PATH`/模型目录指到数据盘。 |
| 5 | **复用 base 镜像的 torch（`--system-site-packages`）** | ≈ 5–7 GiB | 中 | 中 | 避免与 `/root/miniconda3` 的 torch 重复。但 DiffSynth 依赖可能与 base 版本冲突，需验证。 |
| 6 | **outputs 轮转/清理** | 有界（≈30 GB/月） | 中 | 低（旧产物丢失） | 按时间/数量删 `outputs/{videos,images}`；README 无此机制，需新增脚本。 |
| 7 | **HiDream 换量化版** | 若可用省 ~24 GiB | 高 | 高 | **官方无 nf4**。社区有 `drbaph/HiDream-O1-Image-FP8`（8.2 GiB）、`WaveCut/...-SDNQ-4bit-...`（9.9 GiB），但布局与 DiffSynth `HiDreamO1ImagePipeline` 期望的 HF 分片 bf16（`model-*-of-00008.safetensors`）不同，**不能直接 drop-in**，需自定义加载。**结论：不作为省盘手段推荐；DiffSynth 可直接加载的 HiDream 量化版未证实存在。** |
| 8 | **local_dir 直下是否双份** | 0（本就不双份） | — | — | modelscope-hub 源码：`local_dir` 提供时文件**直接写入 local_dir**（`_download.py:600-601`、`:711-712`），不走默认 cache。**无需改动**；但若改用 DiffSynth 的 `ModelConfig(model_id=...)` 会走 `~/.cache/modelscope`（系统盘），要注意。 |

补充：install.sh 的 H3 processor 下载已正确用 `allow_patterns=["FL2VA/processor/*"]`（仅 11 MB），无需改。

## 5. 未证实 / 待现场确认

- **`/autodl-pub` 是否已存在可复用的 H3 / HiDream 权重**：**未证实**。AutoDL 文档只说公共数据可解压到 `/root/autodl-tmp`，未列内容清单；当前环境（WSL）无法枚举该挂载。即使存在，也需现场 `ls` 确认，且只读挂载对推理无影响。
- **`/autodl-pub` 容量「7.3T / 只读」**：AutoDL 官方文档未给出该数字与属性，**未证实**。
- **`.venv` 精确安装体积**：wheel 大小是实测，安装后 6–9 GiB 为估算，需现场 `du -sh .venv` 确认。
- **H3/HiDream 单产出精确体积**：基于官方演示文件与 CRF/分辨率推算，属估算，需现场实测一次。
- **torch 具体版本/是否切 cu13**：取决于安装时 PyPI 最新版，可能与本机 CUDA 驱动匹配情况需现场验证（不影响磁盘结论量级）。

## 6. 一句话给部署

给目标机挂数据盘：**仅 H3 → 50 GB；H3+HiDream → 100 GB**（不做 outputs 轮转再 +30 GB/月）。
同时给 install.sh 的 NF4 下载补 `allow_patterns`（省 44.8 GB），并把 `.venv`/权重/outputs 全部指向数据盘，系统盘只留 OS + miniconda（保留 ≥5 GB 余量）。
