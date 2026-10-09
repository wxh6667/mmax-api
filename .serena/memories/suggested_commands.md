# 常用命令

## 部署机（AutoDL，项目根 /root/autodl-tmp/mmax）

- 安装/更新依赖：`bash scripts/install.sh`
- 启停：`bash scripts/start.sh` / `stop.sh` / `restart.sh`
- 健康检查（协议级，会打真实路由）：`bash scripts/healthcheck.sh`
- 日志：`bash scripts/logs.sh`
- 发布更新：`bash scripts/update.sh`（pull --ff-only + 语法检查 + 重启 + 健康检查）
- 自启动装卸：`install_autostart.sh` / `uninstall_autostart.sh` / `autostart_status.sh`

## 本机开发验证

- Python 语法：`python -m compileall -q mmax_api`
- Shell 语法：`bash -n scripts/<file>.sh`
- 插件语法：`node --input-type=module --check < integrations/new-api/minimax-h3/plugin.js`
- 本地起服务：`python -m mmax_api.run`（需 MMAX_* 环境变量，默认路径指向部署机）

## Trellis

- 查看活动任务：`python3 .trellis/scripts/task.py current`
