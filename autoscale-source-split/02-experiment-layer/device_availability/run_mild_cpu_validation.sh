#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUN_ID="${1:-mild_cpu_validation_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}/results/${RUN_ID}}"
STATE_FILE="${STATE_FILE:-${OUT_DIR}/current_phase.json}"
TARGET_NODE="${TARGET_NODE:-icclz1}"
TARGET_HOST="${TARGET_HOST:-100.105.48.97}"
METRICS_URL="${METRICS_URL:-http://${TARGET_HOST}:9100/metrics}"
PROBE_INTERVAL_SECONDS="${PROBE_INTERVAL_SECONDS:-5}"
COMPUTE_TIMEOUT_MS="${COMPUTE_TIMEOUT_MS:-2000}"
DEGRADED_THRESHOLD_MS="${DEGRADED_THRESHOLD_MS:-1000}"

mkdir -p "${OUT_DIR}"

echo "[INFO] RUN_ID=${RUN_ID}"
echo "[INFO] OUT_DIR=${OUT_DIR}"
echo "[INFO] TARGET_NODE=${TARGET_NODE}"
echo "[INFO] TARGET_HOST=${TARGET_HOST}"
echo "[INFO] Mild CPU validation keeps the same 2s / 1s thresholds."

cleanup() {
  if [[ -n "${STRESS_PID:-}" ]]; then
    kill "${STRESS_PID}" 2>/dev/null || true
  fi
  if [[ -n "${PROBE_PID:-}" ]]; then
    kill "${PROBE_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

OUT_DIR="${OUT_DIR}" \
STATE_FILE="${STATE_FILE}" \
EXPERIMENT_PROFILE=cpu_smoke \
BASELINE_SECONDS="${BASELINE_SECONDS:-1200}" \
CPU_M_SECONDS="${CPU_M_SECONDS:-1200}" \
RECOVERY_1_SECONDS="${RECOVERY_1_SECONDS:-600}" \
CPU_M_WORKERS="${CPU_M_WORKERS:-2}" \
bash "${SCRIPT_DIR}/stress_runner.sh" "${RUN_ID}" &
STRESS_PID=$!

python3 "${SCRIPT_DIR}/availability_probe.py" \
  --target-node "${TARGET_NODE}" \
  --target-host "${TARGET_HOST}" \
  --metrics-url "${METRICS_URL}" \
  --interval-seconds "${PROBE_INTERVAL_SECONDS}" \
  --compute-timeout-ms "${COMPUTE_TIMEOUT_MS}" \
  --degraded-threshold-ms "${DEGRADED_THRESHOLD_MS}" \
  --phase-file "${STATE_FILE}" \
  --stop-phase-name COMPLETE \
  --out-dir "${OUT_DIR}" &
PROBE_PID=$!

wait "${STRESS_PID}"
wait "${PROBE_PID}"

trap - EXIT
echo "[INFO] mild CPU validation completed"
