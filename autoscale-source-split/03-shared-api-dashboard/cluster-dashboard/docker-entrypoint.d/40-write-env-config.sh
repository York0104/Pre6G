#!/bin/sh
set -eu

cat > /usr/share/nginx/html/env-config.js <<EOF
window.__PRE6G_DASHBOARD_CONFIG__ = {
  apiBase: "${PRE6G_DASHBOARD_API_BASE:-http://127.0.0.1:8000}",
  apiToken: "${PRE6G_DASHBOARD_API_TOKEN:-}"
};
EOF
