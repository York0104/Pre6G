#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUN_ID="${1:-baseline_diagnosis_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}/results/${RUN_ID}}"
STATE_FILE="${STATE_FILE:-${OUT_DIR}/current_phase.json}"
TIMELINE_FILE="${TIMELINE_FILE:-${OUT_DIR}/phase_timeline.jsonl}"
TARGET_NODE="${TARGET_NODE:-icclz1}"
TARGET_HOST="${TARGET_HOST:-100.105.48.97}"
METRICS_URL="${METRICS_URL:-http://${TARGET_HOST}:9100/metrics}"
DURATION_SECONDS="${DURATION_SECONDS:-1200}"
PROBE_INTERVAL_SECONDS="${PROBE_INTERVAL_SECONDS:-5}"
COMPUTE_TIMEOUT_MS="${COMPUTE_TIMEOUT_MS:-2000}"
DEGRADED_THRESHOLD_MS="${DEGRADED_THRESHOLD_MS:-1000}"

mkdir -p "${OUT_DIR}"

write_state() {
  local phase_name="$1"
  local duration_seconds="$2"
  cat > "${STATE_FILE}" <<EOF
{
  "phase_name": "${phase_name}",
  "cpu_load_percent": 0,
  "memory_size_percent": 0,
  "duration_seconds": ${duration_seconds},
  "target_node": "${TARGET_NODE}",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
  printf '{"timestamp":"%s","phase_name":"%s","cpu_load_percent":0,"memory_size_percent":0,"duration_seconds":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "${phase_name}" \
    "${duration_seconds}" >> "${TIMELINE_FILE}"
}

cleanup() {
  if [[ -n "${PROBE_PID:-}" ]]; then
    kill "${PROBE_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "[INFO] RUN_ID=${RUN_ID}"
echo "[INFO] OUT_DIR=${OUT_DIR}"
echo "[INFO] TARGET_NODE=${TARGET_NODE}"
echo "[INFO] TARGET_HOST=${TARGET_HOST}"
echo "[INFO] DURATION_SECONDS=${DURATION_SECONDS}"
echo "[INFO] COMPUTE_TIMEOUT_MS=${COMPUTE_TIMEOUT_MS}"
echo "[INFO] DEGRADED_THRESHOLD_MS=${DEGRADED_THRESHOLD_MS}"

write_state "BASELINE" "${DURATION_SECONDS}"

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

sleep "${DURATION_SECONDS}"
write_state "COMPLETE" "0"
wait "${PROBE_PID}"

trap - EXIT
echo "[INFO] baseline diagnosis completed"
