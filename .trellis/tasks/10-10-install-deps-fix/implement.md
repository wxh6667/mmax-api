# Implement — install.sh 依赖安装修复

> 执行顺序自上而下；每步给出验证方式。改动仅限 `scripts/install.sh`（必要时 `.env.example`）。

## 0. 前置：拿到实机基础环境版本（决定 D2/D3 取值）

```bash
python3 -c "import torch, sys; print(sys.executable, torch.__version__, torch.version.cuda)"
python3 -c "import transformers, sys; print(transformers.__version__)" 2>/dev/null || echo "no transformers in base"
nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null || echo "no GPU (无卡模式)"
```

- **Gate A 已解除（2026-10-10 实测）**：`python3` = `/root/miniconda3/bin/python3`，自带 `torch 2.8.0+cu128`
  （满足 `torch>=2.0.0`），基础环境无 transformers。→ D3 走主方案（`--system-site-packages`）并自动钉 `torch==2.8.0`。

## 1. 变量与开关（install.sh 顶部，25–27 行附近）

- [ ] 新增 `DIFFSYNTH_EXTRAS`（默认 `audio`）、`DIFFSYNTH_CONSTRAINTS`（默认 `transformers<5`）、
      `VENV_SYSTEM_SITE`（默认 `1`）、`PIP_CACHE_FLAG`（依赖 `MMAX_PIP_NO_CACHE`）。
- [ ] **探测镜像 torch 版本并入约束**（避免 pip 连带升级 torch）：
      仅当 `VENV_SYSTEM_SITE=1` 且探测非空时，把 `torch==<version>` 追加到 `DIFFSYNTH_CONSTRAINTS`：
      ```bash
      base_torch="$(python3 -c 'import torch;print(torch.__version__.split("+")[0])' 2>/dev/null || true)"
      if [[ "$VENV_SYSTEM_SITE" == "1" && -n "$base_torch" ]]; then
        DIFFSYNTH_CONSTRAINTS="$DIFFSYNTH_CONSTRAINTS torch==$base_torch"
      else
        echo "[deps] WARNING: 未复用镜像 torch，将按 pip 默认解析（会下载完整 torch ≈3.6GB）。" >&2
      fi
      ```
- 验证：`bash -n scripts/install.sh`；`echo` 打印最终 `DIFFSYNTH_CONSTRAINTS` 确认含 `torch==2.8.0`。

## 2. venv 创建加 `--system-site-packages` + 既有 venv 一致性检查（78–84 行）

- [ ] 按 `VENV_SYSTEM_SITE` 创建 venv。
- [ ] 新增：若 `.venv` 已存在，读取 `.venv/pyvenv.cfg` 的 `include-system-site-packages`，
      与期望不符时打印 `WARNING` + 提示删除重建（**不擅自删除**）。
- 验证：`bash -n`；手工在已有 venv 上运行，确认告警出现。

## 3. 依赖安装带 extras + 约束（105–109 行）

- [ ] clone 路径：`-e "${DIFFSYNTH_PATH}[${DIFFSYNTH_EXTRAS}]" $DIFFSYNTH_CONSTRAINTS`
- [ ] PyPI 路径：`"diffsynth[${DIFFSYNTH_EXTRAS}]" $DIFFSYNTH_CONSTRAINTS`
- [ ] 三条 `pip install` 改用 `$PIP_CACHE_FLAG`（去掉写死的 `--no-cache-dir`）。
- 验证：`grep -n "no-cache-dir" scripts/install.sh` 只应在 `PIP_CACHE_FLAG` 定义处出现。

## 4. 依赖冒烟校验与 pip 缓存顺序

- [ ] 在**依赖安装完成后、模型下载（≈28GB）之前**插入 import 校验（按 `design.md` D5 的模块清单）；
      失败 `exit 1`，不打印 `INSTALL DONE`。放前面是为了避免下完 28GB 才发现依赖坏。
- [ ] `pip cache purge` 移到**脚本最后一步**（模型下载之后、`INSTALL DONE` 之前），
      确保校验失败时缓存保留、重试不必从零重下。
- 验证：临时把校验改成 import 一个不存在的模块，确认脚本以非零码退出、无 `INSTALL DONE`、
      且 `pip cache purge` 未被执行；改回。

## 5. 文档同步

- [ ] `.env.example`：补 `MMAX_VENV_SYSTEM_SITE` / `MMAX_DIFFSYNTH_EXTRAS` / `MMAX_DIFFSYNTH_CONSTRAINTS` /
      `MMAX_PIP_NO_CACHE` 四个键及默认值说明。
- [ ] **约束示例值必须加引号**（`MMAX_DIFFSYNTH_CONSTRAINTS='transformers<5'`）：`.env` 会被
      `install.sh` `source`，未加引号的 `<` 会被 bash 当成输入重定向，把上界静默截断成无约束的 `transformers`
      —— 恰好复现本任务要修的缺陷。验证：`source` 一份样例 `.env` 后核对变量值。
- [ ] `README.md`（若存在部署段落）：说明依赖安装复用镜像 torch 与 `[audio]` extra。

## 6. 端到端验证（AutoDL GPU 模式）

- [ ] 删除旧 `.venv` 后 `bash scripts/install.sh` 全流程跑通（**删除 `.venv` 前先确认其中无手工内容**）。
- [ ] `python -c "import torchaudio, av, torch; print(torch.__version__, torch.cuda.is_available())"`。
- [ ] `python -c "from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Pipeline"`。
- [ ] 记录实际解析版本，确认 `transformers` 满足约束。
- [ ] 重复运行 `install.sh` 幂等。
- [ ] 起服务发一条 H3 请求，确认走到推理而非 import 失败。

## Review Gates

- **Gate A（步骤 0 后）**：镜像 torch 可用性 → 决定 D3 走主方案还是备选。
- **Gate B（步骤 3 后）**：`shellcheck` 通过 + `[audio]` 出现在两条路径。
- **Gate C（步骤 6）**：冒烟与 H3 实机请求通过，否则不得报告完成。

## Rollback Points

- 改动全部在 `scripts/install.sh` 一个文件内、无数据/配置破坏性操作，回滚即 `git restore scripts/install.sh`。
- 已存在的 `.venv` 不会被脚本删除；若需回到隔离 venv，删除 `.venv` 后以 `MMAX_VENV_SYSTEM_SITE=0` 重跑。
- 模型权重、`.env`、`.api_key` 不受本任务影响。
