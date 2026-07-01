#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-4174}"
NODE22_BIN="${NODE22_BIN:-/home/icclz2/.local/node22/bin}"
NODE22_ROOT="${NODE22_ROOT:-/home/icclz2/.local/node22}"

export PATH="${NODE22_BIN}:$PATH"

NODE_BIN="${NODE_BIN:-$NODE22_BIN/node}"
NPM_CLI_JS="${NPM_CLI_JS:-$NODE22_ROOT/lib/node_modules/npm/bin/npm-cli.js}"

npm_cmd() {
  "$NODE_BIN" "$NPM_CLI_JS" "$@"
}

if [[ ! -x "$NODE_BIN" ]]; then
  echo "[ERROR] node runtime not found: $NODE_BIN" >&2
  exit 1
fi

if [[ ! -f "$NPM_CLI_JS" ]]; then
  echo "[ERROR] npm cli not found: $NPM_CLI_JS" >&2
  exit 1
fi

cd "$SCRIPT_DIR"

if [[ -f .env ]]; then
  set -a
  # Reuse the same local runtime values used for Vite builds.
  source .env
  set +a
fi

if [[ ! -d node_modules ]]; then
  echo "==> installing frontend dependencies"
  npm_cmd install
fi

echo "==> building frontend"
npm_cmd run build

cat > dist/env-config.js <<EOF
window.__PRE6G_DASHBOARD_CONFIG__ = {
  apiBase: "${PRE6G_DASHBOARD_API_BASE:-${VITE_AUTOSCALE_API_BASE:-http://127.0.0.1:8000}}",
  apiToken: "${PRE6G_DASHBOARD_API_TOKEN:-${VITE_AUTOSCALE_API_TOKEN:-}}"
};
EOF

exec "$NODE_BIN" "$NPM_CLI_JS" run preview -- --host "$HOST" --port "$PORT"
