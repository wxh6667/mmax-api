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

curl -fsS "http://${HOST}:${PORT}/health"
echo
