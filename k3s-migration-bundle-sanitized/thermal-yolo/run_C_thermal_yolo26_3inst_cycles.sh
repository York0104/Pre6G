#!/usr/bin/env bash
set -euo pipefail

CYCLES="${CYCLES:-2}"
SLEEP_BETWEEN_CYCLES="${SLEEP_BETWEEN_CYCLES:-120}"

WORKER_NODE="${WORKER_NODE:-icclz1}"
WORKER_USER="${WORKER_USER:-icclz1}"
WORKER_IP="${WORKER_IP:-100.105.48.97}"
WORKER_REPO="${WORKER_REPO:-/home/icclz1/gpu-tempctl-lab}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${EXP_RUNS_DIR:-${HOME}/exp_runs}}"
RUN_ID_PREFIX="${RUN_ID_PREFIX:-C_thermal_yolo26_3inst}"

PRE_NORMAL_SEC="${PRE_NORMAL_SEC:-120}"
RAMP_UP_SEC="${RAMP_UP_SEC:-60}"
HIGH_HOLD_SEC="${HIGH_HOLD_SEC:-300}"
RAMP_DOWN_SEC="${RAMP_DOWN_SEC:-60}"
POST_NORMAL_SEC="${POST_NORMAL_SEC:-180}"

FOCUS_INTERVAL="${FOCUS_INTERVAL:-0.2}"
BG_INTERVAL="${BG_INTERVAL:-0.3}"

CURRENT_CHILD_PID=""

kill_tree() {
  local pid="${1:-}"
  if [ -z "${pid}" ] || ! kill -0 "${pid}" >/dev/null 2>&1; then
    return 0
  fi

  local child
  for child in $(pgrep -P "${pid}" 2>/dev/null || true); do
    kill_tree "${child}"
  done

  kill "${pid}" >/dev/null 2>&1 || true
}

cleanup_current_child() {
  local rc=$?
  trap - EXIT INT TERM

  if [ -n "${CURRENT_CHILD_PID}" ]; then
    echo "[INFO] stopping active cycle process pid=${CURRENT_CHILD_PID}"
    kill_tree "${CURRENT_CHILD_PID}"
    wait "${CURRENT_CHILD_PID}" >/dev/null 2>&1 || true
  fi

  exit "${rc}"
}

trap cleanup_current_child EXIT INT TERM

echo "[INFO] CYCLES=${CYCLES}"
echo "[INFO] WORKER=${WORKER_USER}@${WORKER_IP}"
echo "[INFO] OUTPUT_ROOT=${OUTPUT_ROOT}"
echo "[INFO] RUN_ID_PREFIX=${RUN_ID_PREFIX}"
echo "[INFO] phase seconds: pre=${PRE_NORMAL_SEC}, ramp_up=${RAMP_UP_SEC}, high=${HIGH_HOLD_SEC}, ramp_down=${RAMP_DOWN_SEC}, post=${POST_NORMAL_SEC}"

for i in $(seq 1 "$CYCLES"); do
  RUN_ID="${RUN_ID_PREFIX}_cycle${i}_$(date +%Y%m%d_%H%M%S)"
  RUN_DIR="${OUTPUT_ROOT}/${RUN_ID}"

  echo
  echo "============================================================"
  echo "[INFO] START cycle ${i}/${CYCLES}: ${RUN_ID}"
  echo "============================================================"

  WORKER_NODE="${WORKER_NODE}" \
  WORKER_USER="${WORKER_USER}" \
  WORKER_IP="${WORKER_IP}" \
  OUTPUT_ROOT="${OUTPUT_ROOT}" \
  PRE_NORMAL_SEC="${PRE_NORMAL_SEC}" \
  RAMP_UP_SEC="${RAMP_UP_SEC}" \
  HIGH_HOLD_SEC="${HIGH_HOLD_SEC}" \
  RAMP_DOWN_SEC="${RAMP_DOWN_SEC}" \
  POST_NORMAL_SEC="${POST_NORMAL_SEC}" \
  FOCUS_INTERVAL="${FOCUS_INTERVAL}" \
  BG_INTERVAL="${BG_INTERVAL}" \
  THERMAL_CMD="WORKER_HOST=${WORKER_IP} WORKER_USER=${WORKER_USER} WORKER_REPO=${WORKER_REPO} WARMUP_SECONDS=${PRE_NORMAL_SEC} NORMAL_HOLD_SECONDS=${PRE_NORMAL_SEC} FAULT_HOLD_SECONDS=${HIGH_HOLD_SEC} STABLE_SECONDS=20 bash ${HOME}/AutoScale/experiments/thermal_analysis/run_cycle_from_master.sh" \
  bash "${HOME}/AutoScale/scripts/run_B_thermal_yolo26_3inst.sh" "${RUN_ID}" &
  CURRENT_CHILD_PID=$!
  wait "${CURRENT_CHILD_PID}"
  CURRENT_CHILD_PID=""

  echo "[INFO] build dataset for ${RUN_ID}"
  python "${HOME}/AutoScale/experiments/thermal_analysis/build_thermal_yolo_dataset.py" \
    --run-dir "${RUN_DIR}" \
    --merge-tolerance-sec 2

  VM_AGGREGATOR_ENABLED="${VM_AGGREGATOR_ENABLED:-1}"
  VM_AGGREGATOR_AUTO_MERGE="${VM_AGGREGATOR_AUTO_MERGE:-1}"
  VM_AGGREGATOR_MERGE_TOLERANCE_SEC="${VM_AGGREGATOR_MERGE_TOLERANCE_SEC:-5}"
  if [ "${VM_AGGREGATOR_ENABLED}" = "1" ] && [ "${VM_AGGREGATOR_AUTO_MERGE}" = "1" ]; then
    echo "[INFO] merge VM aggregator metrics for ${RUN_ID}"
    python "${HOME}/AutoScale/experiments/thermal_analysis/merge_vmagg_into_thermal_dataset.py" \
      --run-dir "${RUN_DIR}" \
      --vmagg-csv "${RUN_DIR}/metrics/vm_aggregator_${WORKER_NODE}.csv" \
      --tolerance-sec "${VM_AGGREGATOR_MERGE_TOLERANCE_SEC}" \
      > "${RUN_DIR}/logs/vm_aggregator_merge_after_build.log" 2>&1 || {
        echo "[WARN] VM aggregator merge failed; see ${RUN_DIR}/logs/vm_aggregator_merge_after_build.log"
      }
  fi

  echo "[INFO] plot dataset for ${RUN_ID}"
  python "${HOME}/AutoScale/experiments/thermal_analysis/plot_thermal_yolo_dataset.py" \
    --run-dir "${RUN_DIR}"

  echo "[INFO] finished cycle ${i}/${CYCLES}: ${RUN_ID}"

  if [ "$i" -lt "$CYCLES" ]; then
    echo "[INFO] sleep ${SLEEP_BETWEEN_CYCLES}s before next cycle"
    sleep "${SLEEP_BETWEEN_CYCLES}"
  fi
done
