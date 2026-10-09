# 代码约定

- 注释、docstring、日志、API 错误消息全部使用简体中文。
- 模块级单例：`settings`（config）、`jobs`（jobs）、`scheduler`（scheduler）、`h3_backend`/`hidream_backend`（各自模块尾部实例化）。
- 错误处理：HTTP 层统一抛 `APIError(status, message, code, param)`，由 exception handler 转 OpenAI 风格错误体；后端层直接 raise RuntimeError/ValueError，由 scheduler 捕获标记任务 failed。
- 参数解析集中在 api.py 的 `_parse_*` 系列辅助函数；JSON 与 multipart 双格式靠 `request.json() if "application/json" in content_type else request.form()` 区分。
- 后端懒加载：`_pipe` 首次 generate 时 `_load()`；日志用 `print(..., flush=True)`（run.py 统一加北京时间前缀，不要改用 logging）。
- 配置只走 `MMAX_*` 环境变量 + config.py 的 frozen Settings，不引入其它配置来源。
- 生成参数（steps/cfg/shift 等）支持请求级覆盖，默认值取 settings；多参考主体驱动默认 shift 用 `hidream_subject_shift`。
