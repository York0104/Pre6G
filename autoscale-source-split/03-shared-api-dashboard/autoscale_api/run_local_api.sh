#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
HOST_ENV_FILE="${HOST_ENV_FILE:-$ROOT_DIR/autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env}"
AUTOSCALE_ENV_FILE="${AUTOSCALE_ENV_FILE:-$ROOT_DIR/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/iccl/bin/python}"

if [[ -f "$HOST_ENV_FILE" ]]; then
  set -a
  . "$HOST_ENV_FILE"
  set +a
fi

if [[ -f "$AUTOSCALE_ENV_FILE" ]]; then
  set -a
  . "$AUTOSCALE_ENV_FILE"
  set +a
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[ERROR] Python runtime not found: $PYTHON_BIN" >&2
  echo "[ERROR] Set PYTHON_BIN to a valid interpreter, or create the repo-local 'iccl' env before starting autoscale_api." >&2
  exit 1
fi

export HOME="${HOME:-/home/icclz2}"
export KUBECONFIG="${KUBECONFIG:-/home/icclz2/.kube/config}"
export PYTHONPATH="$ROOT_DIR/autoscale-source-split/03-shared-api-dashboard/autoscale_api:$ROOT_DIR/autoscale-source-split/01-monitoring-layer"

cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" -m uvicorn app.main:app --host "${AUTOSCALE_API_HOST:-0.0.0.0}" --port "${AUTOSCALE_API_PORT:-8000}"
