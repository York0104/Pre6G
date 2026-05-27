#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5174}"

if ! command -v node >/dev/null 2>&1; then
  echo "[ERROR] node is not installed on this machine." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[ERROR] npm is not installed on this machine." >&2
  exit 1
fi

cd "$SCRIPT_DIR"
if [[ ! -d node_modules ]]; then
  echo "==> installing frontend dependencies"
  npm install
fi

exec npm run dev -- --host "$HOST" --port "$PORT"
