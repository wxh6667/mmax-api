#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

HOST="${MMAX_HEALTH_HOST:-127.0.0.1}"
PORT="${MMAX_PORT:-6006}"
BASE_URL="http://${HOST}:${PORT}"
PYTHON_BIN="${MMAX_PYTHON_BIN:-$ROOT/.venv/bin/python}"

echo "===== 服务健康状态 ====="
curl -fsS "${BASE_URL}/health"
echo

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "找不到 Python：$PYTHON_BIN"
  exit 1
fi

echo "===== 核心 API 路由 ====="
OPENAPI_JSON="$(curl -fsS "${BASE_URL}/openapi.json")"
printf '%s' "$OPENAPI_JSON" | "$PYTHON_BIN" -c '
import json, sys
spec = json.load(sys.stdin)
required = {
    ("/v1/images/generations", "post"),
    ("/v1/images/edits", "post"),
    ("/v1/videos", "post"),
    ("/v1/videos/{job_id}", "get"),
    ("/v1/videos/{job_id}/content", "get"),
}
paths = spec.get("paths", {})
missing = []
for path, method in sorted(required):
    methods = paths.get(path, {})
    ok = method in methods
    print(f"{method.upper():4} {path}: {\"OK\" if ok else \"MISSING\"}")
    if not ok:
        missing.append(f"{method.upper()} {path}")
if missing:
    print("缺少核心路由：" + ", ".join(missing), file=sys.stderr)
    sys.exit(1)
'

echo "协议健康检查通过。"
