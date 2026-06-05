#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "Using PYTHON_BIN=$PYTHON_BIN"
echo "AUTOSCALE_API_BASE=${AUTOSCALE_API_BASE:-}"
echo "OUTPUT_ROOT=${OUTPUT_ROOT:-$HOME/node_metric_csv_logs}"
echo "INTERVAL_SECONDS=${INTERVAL_SECONDS:-30}"

exec "$PYTHON_BIN" collect_full_metrics_api_csv_standalone.py
