#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$ROOT/scripts/stop.sh"
bash "$ROOT/scripts/start.sh"
