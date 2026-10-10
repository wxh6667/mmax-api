# install.sh 依赖栈调研：为什么装得又慢、又"感觉不对"

> 针对用户反馈"为什么下载的依赖这么多/这么慢"、"总感觉不太对"的 GitHub + PyPI 一手调研。
> 结论：**装得慢是表象，真正的问题是依赖栈装错了 —— H3 后端在当前安装方式下连 import 都会失败。**

---

## 1. Problem Profile

- 目标：在 AutoDL GPU 容器上 `bash scripts/install.sh` 完成部署，`mmax-api` 的 H3 视频 / HiDream 图片两条后端可用。
- 现象：
  - 依赖下载巨大且慢（torch + CUDA wheels ≈3.6GB，实测 ~600kB/s）。
  - 用户主观"总感觉不太对"。
- 环境：AutoDL 容器；`install.sh` 新建隔离 venv（`python3 -m venv .venv`，**不带** `--system-site-packages`）。
- 本地约束（`mmax-api/pyproject.toml`）：只声明 `fastapi/uvicorn/python-multipart/Pillow/safetensors`；
  **没有** `torch`、`diffsynth`、`av`、`torchaudio`。运行时的重型依赖全部来自 `diffsynth`。

## 2. Search Path

- 检索面：PyPI JSON API（`diffsynth` 包元数据/发布时间）、GitHub REST（repo 元数据、contents、commits 取模块引入时间）、
  GitHub Search Issues/PRs、DiffSynth-Studio 仓库源码（`pyproject.toml`、管线与 utils 模块的顶层 import）。
- 未使用 subagent：问题收敛在单一依赖（`diffsynth`）单一生态，直接一手核对即可。

## 3. 关键发现

### 3.1 ✅ 反驳假设：PyPI fallback 不是"装错了包"

`install.sh:96` GitHub 浅克隆失败（503）时回退 `pip install diffsynth`（`install.sh:108`）。经核对：

- PyPI `diffsynth` 即 **ModelScope 官方发布**（作者 ModelScope Team），**不是**第三方同名包。
- PyPI `2.1.9` 发布时间与仓库 `pushed_at` 仅相隔约 71 秒，即 ≈ 仓库 HEAD。
- mmax 需要的 4 个模块在 2.1.9 中均存在：
  `pipelines/minimax_h3_audio_video.py`（2026-08-03 引入）、`pipelines/hidream_o1_image.py`（2026-05-14）、
  `utils/data/audio_video.py`、`core/loader/config.ModelConfig`。

→ **回退到 PyPI 是安全的**，"必须用仓库 HEAD"的担忧不成立。问题不在包来源。

### 3.2 ❌ 硬阻断：缺 `[audio]` extra，H3 后端 import 即失败

`diffsynth` 把音频相关依赖放在 **可选 extra** 里（`pyproject.toml`）：

```toml
dependencies = ["torch>=2.0.0", "torchvision", "transformers", "imageio[ffmpeg]",
                "safetensors", "einops", "modelscope", "ftfy", "pandas", "accelerate", "peft"]

[project.optional-dependencies]
audio = ["av", "torchaudio", "torchcodec", "librosa"]   # ← 默认不装
```

而 mmax 的 H3 路径**会**触发这两个依赖，且是**顶层 import**：

| 触发点 | 链条 | 性质 |
|---|---|---|
| `mmax_api/backends/h3.py:86` `from diffsynth.pipelines.minimax_h3_audio_video import ...` | `minimax_h3_audio_video.py:20` → `from ..utils.data.audio import ...` → `utils/data/audio.py:2` = `import torchaudio` | **import 时即失败** |
| `mmax_api/backends/h3.py:116` `from diffsynth.utils.data.audio_video import write_video_audio` | `utils/data/audio_video.py:1` = `import av` | **生成时失败** |

`install.sh` 两条路径都是**裸装**，都不带 extra：

```bash
# install.sh:106   克隆成功路径
"$PYTHON_BIN" -m pip install --no-cache-dir -e "$DIFFSYNTH_PATH"
# install.sh:108   回退 PyPI 路径
"$PYTHON_BIN" -m pip install --no-cache-dir diffsynth
```

且 mmax 自身 `pyproject.toml` 未声明 `av`/`torchaudio`，venv 又是隔离的（不带 `--system-site-packages`），
`transformers`/`imageio[ffmpeg]`/`modelscope` 也不会把 `av`/`torchaudio` 带进来。

→ **结论：当前安装方式下，`/health` 看似正常，但第一条 H3 请求会在 import 阶段抛
`ModuleNotFoundError: No module named 'torchaudio'`（或 `av`）。** 这正是"感觉不对"的根因。

> 注：HiDream 路径（`hidream_o1_image.py`）顶层不 import `av`/`torchaudio`（`transformers` 是函数内延迟 import），
> 因此图片后端可能不受影响 —— 该缺陷是 **H3 专属**。

### 3.3 ⚠️ 无版本上界 → 解析出 torch 2.14.1 / CUDA 13 / transformers 5.19

`diffsynth` 对关键依赖几乎不设上界：`torch>=2.0.0`、`transformers`（完全无约束）、`torchvision`（无约束）。
因此 pip 会解析到当下最新，带来两类风险：

1. **transformers 5.x 兼容性未完成**（有明确证据）：
   - PR [#1717](https://github.com/modelscope/DiffSynth-Studio/pull/1717) `fix(metrics): load AestheticModel checkpoint on transformers<5` —— **已合并**，为 `transformers<5` 打补丁，说明 5.x 曾破坏功能。
   - PR [#1434](https://github.com/modelscope/DiffSynth-Studio/pull/1434) `flux2: ... transformers 5.8 compat ...` —— **仍 open**，5.x 兼容工作未收口。
   - 官方 `nexusgen` extra 直接钉 `transformers==4.49.0`；`npu` extra 钉 `torch==2.7.1` —— 官方在有需要时会钉版本，说明 4.x 才是被验证的组合。
2. **CUDA 13 wheels 需要很新的显卡驱动**：`torch 2.14.1+cu130` 要求宿主机驱动达到 CUDA 13 的最低版本；
   AutoDL 镜像自带驱动若偏低，会出现"装了 GPU 版却 `torch.cuda.is_available() == False`"，且要额外下 ≈3.6GB。

### 3.4 ⚠️ 次要：venv 重复了镜像已有的 torch；`--no-cache-dir` 拖慢重试

- AutoDL 镜像的基础环境本就带一套与本机 CUDA 匹配的 torch；新建隔离 venv 会**再下一整套**（≈3.6GB），
  既慢又是驱动不匹配的来源。这正是 10-10 PRD 里列为"后续评估"的 `--system-site-packages` 议题。
- `install.sh` 全流程 `--no-cache-dir`：好处是不留残渣，但在这条 ~600kB/s 的链路上，**任何一步失败重试都要从零重下**。

## 4. 建议方案（按优先级）

| 优先级 | 改动 | 理由 |
|---|---|---|
| **P0** | 装 extra：`pip install -e "${DIFFSYNTH_PATH}[audio]"` / `pip install "diffsynth[audio]"` | 修复 H3 import 硬阻断，是本轮真正的 bug |
| **P1** | 给 `transformers` 加上界（如 `transformers<5`），必要时同时钉 `torch`/`torchvision` | DiffSynth 的 transformers-5 兼容未收口；避免解析到未验证版本 |
| **P1** | 复用 AutoDL 镜像自带 torch：venv 加 `--system-site-packages`，或按镜像 CUDA 钉 torch | 省下 ≈3.6GB 下载；规避 cu130 驱动不匹配 |
| **P2** | 安装期保留 pip 缓存、**成功后**再 `pip cache purge` | 慢链路上重试不必从零重下；仍不留残渣 |

## 5. Verification Standard（须在 AutoDL GPU 模式实机验证）

1. `python -c "import torchaudio, av; import torch; print(torch.__version__, torch.cuda.is_available())"`
   —— 三者齐全且 CUDA 可用。
2. `python -c "from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Pipeline"` —— 不再抛 `ModuleNotFoundError`。
3. 起服务发一条 H3 请求，确认走到推理而非 import 失败。
4. 记录实际解析出的 `torch/torchvision/transformers` 版本，确认与镜像驱动匹配。

## 6. Confidence

- 3.1 / 3.2：**高**。均为源码级一手证据（顶层 import + pyproject extra 定义 + mmax 未声明），可复现。
- 3.3：**中高**。transformers-5 兼容未收口有已合并/未合并 PR 佐证；CUDA 13 驱动要求属通用事实，具体阈值需按镜像实测。
- 结论方向明确；**修复的具体钉版取值应在任务 design 阶段结合 AutoDL 镜像实际 torch/CUDA 版本确定**。
