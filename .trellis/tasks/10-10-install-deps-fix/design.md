# Design — 依赖安装修复

## 1. 边界

- 改动集中在 `scripts/install.sh` 的 **依赖安装段（现 78–113 行）** 与 **末尾清理段（177–184 行）**；
  在 `INSTALL DONE` 之前新增一段冒烟校验。
- 不动模型下载段、不动 `mmax_api/` 运行逻辑。

## 2. 关键设计决策

### D1 — extras 安装写法（修复 H3 import 硬阻断）

`[audio]` 必须落在引号内，避免 `[` 被当 glob：

```bash
# 克隆成功路径（install.sh:106）
"$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG -e "${DIFFSYNTH_PATH}[${DIFFSYNTH_EXTRAS}]" $DIFFSYNTH_CONSTRAINTS
# PyPI 回退路径（install.sh:108）
"$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG "diffsynth[${DIFFSYNTH_EXTRAS}]" $DIFFSYNTH_CONSTRAINTS
```

`DIFFSYNTH_EXTRAS` 默认 `audio` —— 该 extra 同时带 `av`/`torchaudio`/`torchcodec`/`librosa`，
其中 `av`、`torchaudio` 是顶层 import 的硬需求，`torchcodec` 仅在函数内延迟使用（带上无害）。

> **已知风险，刻意不做回退**：`torchcodec` 是二进制包、对系统 FFmpeg 敏感，理论上可能解析/加载失败。
> 设计上**不**加"失败就退回只装 `av torchaudio`"的兜底——那会装出一个缺 `torchcodec` 却仍能通过
> 冒烟校验的隐性降级环境，比直接失败更危险。若真失败，pip 会响亮报错；此时应先修 FFmpeg/版本，
> 而不是绕开依赖。

### D2 — 版本约束载体：追加 requirement，不引入 constraints 文件

`diffsynth` 的 `transformers` 无上界，直接用追加 requirement 覆盖，避免多一份事实来源：

```bash
DIFFSYNTH_CONSTRAINTS="${MMAX_DIFFSYNTH_CONSTRAINTS:-transformers<5}"
```

- 默认 `<5` 的依据：DiffSynth 的 transformers-5 兼容未收口（PR #1717 已合并补丁、PR #1434 仍 open），
  官方 `nexusgen` extra 自身钉 `transformers==4.49.0`。**该默认值须在实机验证 H3 管线可用后固化**。
- **复用镜像 torch 时（D3 主方案），自动追加 `torch==<检测到的镜像版本>`**（本机实测 `2.8.0`）。
  原因：`diffsynth` 的 `torchvision` 与 `[audio]` 里的 `torchaudio` **同样无上界**；不钉 torch 时，
  pip 解析最新 torchvision 会连带把 torch 升回 2.14.1 —— 复用的意义被抵消，又白下 ≈3.6GB。
  钉住 torch 后，pip 只能挑与之配套的 torchvision/torchaudio。该钉版由脚本**运行时探测**得出，不写死。
- 若复用失败（`MMAX_VENV_SYSTEM_SITE=0` 或探测不到镜像 torch），则不追加 torch 钉版，
  按 pip 默认解析并**显式告警**（会下载完整 torch，慢/大）。

### D3 — 复用镜像自带 torch：venv 走 `--system-site-packages`

**实机确认（2026-10-10）**：`python3` 解析为 `/root/miniconda3/bin/python3`，自带 `torch 2.8.0+cu128`
（满足 `torch>=2.0.0`）；基础环境**无** transformers（将由 pip 装进 venv，符合预期、体积小）。→ **主方案成立**。

```bash
VENV_SYSTEM_SITE="${MMAX_VENV_SYSTEM_SITE:-1}"
if [[ "$VENV_SYSTEM_SITE" == "1" ]]; then
  python3 -m venv --system-site-packages "$ROOT/.venv"
else
  python3 -m venv "$ROOT/.venv"
fi
```

- 目的：让 `torch>=2.0.0` 由镜像基础环境满足，省下 ≈3.6GB 下载，且 torch/CUDA 与镜像驱动天然匹配。
- **已有 `.venv` 时该属性无法更改**：脚本读取 `.venv/pyvenv.cfg` 的 `include-system-site-packages`，
  与期望不符时**明确告警并提示删除重建**（不擅自删除用户 venv —— 删除需用户授权）。
- 风险与缓解：系统包可能污染（旧 `numpy`/`Pillow`/`fastapi`）。D5 冒烟校验会 **import** 关键包并打印其版本，
  这能发现"包缺失"，但**不能**证明版本正确——旧版本遮蔽只能靠打印出的版本人工核对。这是已知的残余风险。
- 备选（若实机发现镜像 torch 过旧而不满足 `torch>=2.0.0`）：退回显式钉版本，由 `MMAX_VENV_SYSTEM_SITE=0` +
  `MMAX_DIFFSYNTH_CONSTRAINTS` 组合表达，无需改脚本结构。

### D4 — pip 缓存策略翻转（安装期留缓存，成功后 purge）

```bash
if [[ "${MMAX_PIP_NO_CACHE:-0}" == "1" ]]; then PIP_CACHE_FLAG="--no-cache-dir"; else PIP_CACHE_FLAG=""; fi
```

- 理由：~600kB/s 链路上，`--no-cache-dir` 使任何失败都要从零重下；保留缓存后，失败重试只需补差量。
- 原"不留残渣"目标由 `pip cache purge` 继续保证，但它被放到**脚本最后一步、冒烟校验之后**：
  校验失败即 `exit 1`、缓存保留（重试不重下）；只有校验通过才 purge。purge 失败仍显式告警，不谎报成功。

### D5 — 安装末尾冒烟校验（把"装完即坏"提前暴露）

放在**依赖安装完成后、模型下载（≈28GB）之前**：慢链路上先失败远比下完 28GB 再失败划算。
失败即 `exit 1`，**不打印 `INSTALL DONE`**：

```bash
"$PYTHON_BIN" - <<'PY'
import importlib

for mod in ("torch", "torchvision", "torchaudio", "av", "transformers", "fastapi", "uvicorn"):
    importlib.import_module(mod)
from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Pipeline  # noqa: F401

import fastapi, torch, torchvision, transformers, uvicorn

print(f"[verify] torch={torch.__version__} torchvision={torchvision.__version__} "
      f"cuda={torch.cuda.is_available()} transformers={transformers.__version__} "
      f"fastapi={fastapi.__version__} uvicorn={uvicorn.__version__}")
PY
```

- 这条校验同时覆盖 D1（av/torchaudio 齐全）与 D3（能打印实际 torch 版本）。
- 注意：无卡模式（无 GPU）下 `cuda=False` 属预期，**不因此判失败**；只要求 import 成功。

## 3. 契约（env keys）

| 键 | 默认 | 含义 |
|---|---|---|
| `MMAX_VENV_SYSTEM_SITE` | `1` | venv 使用 `--system-site-packages` 以复用镜像 torch；设 `0` 退回隔离 venv |
| `MMAX_DIFFSYNTH_EXTRAS` | `audio` | 安装 diffsynth 时附加的 extras |
| `MMAX_DIFFSYNTH_CONSTRAINTS` | `transformers<5` | 追加的版本约束（空格分隔多个） |
| `MMAX_PIP_NO_CACHE` | 未设 | 设 `1` 恢复 `--no-cache-dir`（不保留缓存） |

## 4. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| clone 成功 | `pip install -e "${DIFFSYNTH_PATH}[audio]" transformers<5` |
| clone 失败 | `pip install "diffsynth[audio]" transformers<5` |
| `.venv` 已存在且 system-site 设置与期望不符 | 打印 `WARNING` + 提示删除重建，继续执行（不擅自删 venv） |
| `.venv` 已存在且设置相符 | 静默通过 |
| 复用镜像 torch（默认） | 自动追加 `torch==<镜像版本>`；torchvision/torchaudio 取配套版本，不重下 torch |
| `MMAX_VENV_SYSTEM_SITE=0`（隔离 venv） | 不追加 torch 钉版，stderr 告警"将自行下载完整 torch" |
| 系统无满足 `torch>=2.0.0` 的 torch | 不追加 torch 钉版，由 pip 下载并打印告警（慢/大） |
| `MMAX_DIFFSYNTH_CONSTRAINTS` 已含 torch 钉版 | 不再追加 `torch==<镜像版本>`，打印提示（避免两个冲突的 torch 规格） |
| 冒烟校验任一 import 失败 | stderr 明确错误 + `exit 1`，**不打印 `INSTALL DONE`** |
| `pip cache purge` 失败 | `WARNING`，不中断（沿用现行为） |

## 5. Good / Base / Bad Cases

- **Good**：全新 venv（system-site）→ 复用镜像 torch → 补 `[audio]` + `transformers<5` → 冒烟通过 → purge。
- **Base**：重复运行；`.venv` 已存在且设置相符；依赖齐备，pip 无事可做；校验通过。
- **Bad**：沿用旧脚本 → 无 `[audio]` → 服务能起、`/health` 正常，但第一条 H3 请求
  `ModuleNotFoundError: No module named 'torchaudio'`（当前线上行为）。

## 6. 必做验证

- `bash -n scripts/install.sh` 与 `shellcheck scripts/install.sh` 通过。
- 全新 venv 完整安装后：`torchaudio`/`av` 可 import，`MiniMaxH3Pipeline` 可 import。
- 模拟 clone 失败（如临时将 `MMAX_DIFFSYNTH_PATH` 指向不可写路径，或断网）→ 验证 PyPI 回退路径同样带 extras。
- 重复运行幂等。
- 记录实机解析出的 `torch/torchvision/transformers` 版本。

## 7. Wrong vs Correct

#### Wrong

```bash
# 裸装：不带 [audio]，H3 顶层 import torchaudio 直接失败
"$PYTHON_BIN" -m pip install --no-cache-dir -e "$DIFFSYNTH_PATH"
"$PYTHON_BIN" -m pip install --no-cache-dir diffsynth
# 无校验：装完就打 INSTALL DONE，坏在运行时才暴露
echo "INSTALL DONE."
```

#### Correct

```bash
"$PYTHON_BIN" -m pip install $PIP_CACHE_FLAG -e "${DIFFSYNTH_PATH}[audio]" transformers<5
# ...
"$PYTHON_BIN" -c "import torchaudio, av; from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Pipeline" \
  || { echo "[verify] ERROR: H3 依赖不完整" >&2; exit 1; }
echo "INSTALL DONE."
```
