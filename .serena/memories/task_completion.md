# 任务完成验证

项目无测试集，完成标准是：

1. `python -m compileall -q mmax_api` 通过（CI 同款）。
2. 改过 shell 脚本：`bash -n scripts/<file>.sh` 通过。
3. 改过 New API 插件：`node --input-type=module --check < integrations/new-api/minimax-h3/plugin.js` 通过。
4. 部署机上 `bash scripts/update.sh` 完成发布，健康检查通过（`bash scripts/healthcheck.sh`）。

功能验证用 README 里的 curl 示例（`/v1/images/generations`、`/v1/images/edits`、`/v1/videos`）。
