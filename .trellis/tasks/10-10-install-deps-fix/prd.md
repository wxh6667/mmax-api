# 修复 install.sh 依赖安装：补 [audio] extra 并约束版本

## Goal

让 `scripts/install.sh` 装出的运行环境能**真正跑起 H3 后端**，且依赖解析可控、不重复下载镜像已自带的 torch。

当前有两个叠加缺陷：

1. **H3 后端不可用（硬阻断）**：`install.sh` 装 `diffsynth` 时未带 `[audio]` extra，
   而 H3 路径顶层 import `torchaudio` / `av`（`h3.py:86` → `utils/data/audio.py:2`；`h3.py:116` → `utils/data/audio_video.py:1`），
   mmax 自身也未声明这两个包 → 第一条 H3 请求抛 `ModuleNotFoundError`。
2. **依赖解析到未验证版本**：`diffsynth` 对 `torch`/`transformers` 几无上界，解析出 `torch 2.14.1+cu130` / `transformers 5.x`，
   而 DiffSynth 的 transformers-5 兼容尚未收口（PR #1717 已合并、PR #1434 仍 open），cu130 还要求很新的显卡驱动。

依据与一手证据见 `.trellis/tasks/10-10-install-model-download/research/dependency-stack.md`。

## Requirements

### P0

1. **补齐 `[audio]` extra**：安装 `diffsynth` 时必须带上音频 extra（至少 `av`、`torchaudio`），
   使 H3 后端可 import、可生成。**两条安装路径都要覆盖**：本地 clone 的 `-e` 路径与 GitHub 失败时的 PyPI 回退路径。
2. **约束关键依赖版本**：为 H3 运行所需的关键依赖加上可验证的版本约束，避免解析到 DiffSynth 未验证的
   `transformers` 5.x。约束值须有依据（官方已验证组合 / 官方 extra 钉版），并可通过环境变量覆盖。

### P1

3. **复用镜像自带 torch**：不再另行下载一整套 torch + CUDA wheels（≈3.6GB），改为复用 AutoDL 镜像基础环境
   已有的、与本机驱动匹配的 torch；规避 cu130 与镜像驱动不匹配的风险。
4. **改进 pip 缓存策略**：安装期保留 wheel 缓存（慢链路上重试不必从零重下），**安装成功后**再清理，
   保持"不留残渣"的原目标。

## 约束

- 改动限定在 `scripts/install.sh`（必要时同步 `.env.example` / `README.md` 说明）。
- 不改动模型推理、API、任务队列等运行逻辑。
- 脚本保持幂等、可重复运行；已有 `.env`、`.api_key`、已下模型的复用行为不变。
- **不得用静默兜底掩盖失败**：无法复用镜像 torch 或版本约束无法满足时，必须显式失败或明确回退并告知，
  不允许"装上了但跑不了"的假成功。
- 依赖安装后必须做一次 import 冒烟校验（放在模型下载之前，避免下完几十 GB 才发现依赖坏），
  把"装完即坏"在安装阶段就暴露出来。

## Acceptance Criteria

- [ ] 全新 venv 安装后，`python -c "import torchaudio, av"` 成功（H3 的 import 前置满足）。
- [ ] `python -c "from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Pipeline"` 成功。
- [ ] PyPI 回退路径同样带 `[audio]`（构造 clone 失败场景验证）。
- [ ] 安装后解析出的 `transformers` 版本满足所选约束，且约束有书面依据。
- [ ] 不再重复下载镜像已提供的同版本 torch（或在无法复用时明确说明原因）。
- [ ] 依赖冒烟校验失败时，脚本以明确错误中止、不谎报 `INSTALL DONE`，且 pip 缓存保留（便于重试）。
- [ ] 重复运行 `install.sh` 幂等；`bash -n` 与 `shellcheck` 通过。

## Notes

- 具体版本约束取值、venv 复用镜像 torch 的方式与开关，在 `design.md` 定；**须结合 AutoDL 镜像实际 torch/CUDA 版本**。
- 本任务不覆盖：`/autodl-pub` 复用权重、outputs 轮转脚本。
