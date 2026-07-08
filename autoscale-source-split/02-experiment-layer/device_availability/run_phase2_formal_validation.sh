#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUN_ID="${1:-phase2_formal_validation_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}/results/${RUN_ID}}"
STATE_FILE="${STATE_FILE:-${OUT_DIR}/current_phase.json}"
TARGET_NODE="${TARGET_NODE:-icclz1}"
TARGET_HOST="${TARGET_HOST:-100.105.48.97}"
METRICS_URL="${METRICS_URL:-http://${TARGET_HOST}:9100/metrics}"
PROBE_DRAIN_TIMEOUT_SECONDS="${PROBE_DRAIN_TIMEOUT_SECONDS:-45}"
FINAL_STATE_STATUS="${FINAL_STATE_STATUS:-}"

mkdir -p "${OUT_DIR}"

echo "[INFO] RUN_ID=${RUN_ID}"
echo "[INFO] OUT_DIR=${OUT_DIR}"
echo "[INFO] TARGET_NODE=${TARGET_NODE}"
echo "[INFO] TARGET_HOST=${TARGET_HOST}"
echo "[INFO] METRICS_URL=${METRICS_URL}"
echo "[INFO] This profile follows the current 6h formal validation ladder."
echo "[INFO] Total planned duration is 360 minutes (6h)."

backfill_summary_if_needed() {
  local csv_path="${OUT_DIR}/availability.csv"
  local summary_path="${OUT_DIR}/summary.json"
  if [[ -f "${summary_path}" ]]; then
    return
  fi
  if [[ ! -f "${csv_path}" ]]; then
    return
  fi
  echo "[INFO] summary.json missing; backfilling from availability.csv"
  python3 "${SCRIPT_DIR}/backfill_summary.py" \
    --csv "${csv_path}" \
    --summary-out "${summary_path}" \
    --sample-interval-seconds 5 \
    --target-node "${TARGET_NODE}" || true
}

write_final_state() {
  local status="$1"
  cat > "${STATE_FILE}" <<EOF
{
  "phase_name": "${status}",
  "target_node": "${TARGET_NODE}",
  "run_id": "${RUN_ID}",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
}

cleanup() {
  local signal_name="${1:-EXIT}"
  if [[ -n "${STRESS_PID:-}" ]]; then
    kill "${STRESS_PID}" 2>/dev/null || true
  fi
  if [[ -n "${PROBE_PID:-}" ]]; then
    kill "${PROBE_PID}" 2>/dev/null || true
  fi
  if [[ -n "${FINAL_STATE_STATUS}" ]]; then
    write_final_state "${FINAL_STATE_STATUS}"
  elif [[ "${signal_name}" != "EXIT" ]]; then
    write_final_state "INTERRUPTED"
  fi
  backfill_summary_if_needed
}
trap 'cleanup EXIT' EXIT
trap 'cleanup INT; exit 130' INT
trap 'cleanup TERM; exit 143' TERM

OUT_DIR="${OUT_DIR}" \
STATE_FILE="${STATE_FILE}" \
EXPERIMENT_PROFILE=full_6h \
bash "${SCRIPT_DIR}/stress_runner.sh" "${RUN_ID}" &
STRESS_PID=$!

python3 "${SCRIPT_DIR}/availability_probe.py" \
  --target-node "${TARGET_NODE}" \
  --target-host "${TARGET_HOST}" \
  --metrics-url "${METRICS_URL}" \
  --interval-seconds 5 \
  --phase-file "${STATE_FILE}" \
  --stop-phase-name COMPLETE \
  --out-dir "${OUT_DIR}" &
PROBE_PID=$!

set +e
wait "${STRESS_PID}"
STRESS_EXIT_CODE=$?
set -e

if [[ "${STRESS_EXIT_CODE}" -ne 0 ]]; then
  FINAL_STATE_STATUS="ABORTED"
  echo "[WARN] stress runner exited with code ${STRESS_EXIT_CODE}; stopping probe and backfilling summary if needed"
  kill "${PROBE_PID}" 2>/dev/null || true
else
  for ((i=0; i<PROBE_DRAIN_TIMEOUT_SECONDS; i++)); do
    if ! kill -0 "${PROBE_PID}" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  if kill -0 "${PROBE_PID}" 2>/dev/null; then
    echo "[WARN] probe did not exit within ${PROBE_DRAIN_TIMEOUT_SECONDS}s after stress completion; stopping probe"
    kill "${PROBE_PID}" 2>/dev/null || true
  fi
  FINAL_STATE_STATUS="COMPLETE"
fi

set +e
wait "${PROBE_PID}"
PROBE_EXIT_CODE=$?
set -e

backfill_summary_if_needed

trap - EXIT
if [[ "${STRESS_EXIT_CODE}" -eq 0 && "${PROBE_EXIT_CODE}" -eq 0 ]]; then
  echo "[INFO] phase2 formal validation completed"
else
  echo "[WARN] phase2 formal validation finished with non-zero exit codes: stress=${STRESS_EXIT_CODE} probe=${PROBE_EXIT_CODE}"
fi
