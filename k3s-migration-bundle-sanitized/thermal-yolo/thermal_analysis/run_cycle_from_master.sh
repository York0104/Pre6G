#!/usr/bin/env bash
set -euo pipefail
export NODE_EXPORTER_INSTANCE=100.105.48.97:9100
RUN_ID="${1:-${RUN_ID:?missing run id}}"

AUTOSCALE_DIR="${AUTOSCALE_DIR:-$HOME/AutoScale}"
OUT_DIR="${OUT_DIR:-$HOME/exp_runs/$RUN_ID}"

mkdir -p "$OUT_DIR"

echo "RUN_ID=$RUN_ID"
echo "OUT_DIR=$OUT_DIR"
echo "TARGET=${TARGET:-}"
echo "BAND=${BAND:-}"

TARGET_C="${TARGET_TEMP_C:-${TARGET_TEMP:-${TARGET:-90}}}"
PLOT_TARGET_C="${PLOT_TARGET_C:-${TARGET_TEMP_C:-${TARGET_TEMP:-90}}}"
TARGET="$TARGET_C"
BAND="${BAND:-5}"
LATENCY_GLOB="${LATENCY_GLOB:-$OUT_DIR/raw_latency/*_raw.csv}"

echo "TARGET_C=$TARGET_C"
echo "PLOT_TARGET_C=$PLOT_TARGET_C"
echo "LATENCY_GLOB=$LATENCY_GLOB"

WORKER_HOST="${WORKER_HOST:-100.105.48.97}"
WORKER_USER="${WORKER_USER:-icclz1}"
WORKER_REPO="${WORKER_REPO:-/home/icclz1/gpu-tempctl-lab}"
WORKER_SSH="${WORKER_USER}@${WORKER_HOST}"
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5"

echo "[THERMAL] WORKER_HOST=${WORKER_HOST}"
echo "[THERMAL] WORKER_USER=${WORKER_USER}"
echo "[THERMAL] WORKER_REPO=${WORKER_REPO}"
echo "[THERMAL] WORKER_SSH=${WORKER_SSH}"

ssh ${SSH_OPTS} "${WORKER_SSH}" "
  hostname
  whoami
  test -d '${WORKER_REPO}'
  nvidia-smi --query-gpu=name,temperature.gpu,fan.speed,power.draw --format=csv
"

TARGET_NODE="${TARGET_NODE:-icclz1}"
NAMESPACE_NAME="${NAMESPACE_NAME:-intent-lab}"
INTERVAL_SEC="${INTERVAL_SEC:-1}"
WARMUP_SECONDS="${WARMUP_SECONDS:-120}"
NORMAL_HOLD_SECONDS="${NORMAL_HOLD_SECONDS:-600}"
FAULT_HOLD_SECONDS="${FAULT_HOLD_SECONDS:-300}"
STABLE_SECONDS="${STABLE_SECONDS:-30}"
SAMPLE_INTERVAL="${SAMPLE_INTERVAL:-1.0}"
MIN_DWELL_SECONDS="${MIN_DWELL_SECONDS:-15}"

echo "WARMUP_SECONDS=$WARMUP_SECONDS"
echo "NORMAL_HOLD_SECONDS=$NORMAL_HOLD_SECONDS"
echo "FAULT_HOLD_SECONDS=$FAULT_HOLD_SECONDS"
echo "STABLE_SECONDS=$STABLE_SECONDS"
echo "SAMPLE_INTERVAL=$SAMPLE_INTERVAL"
echo "MIN_DWELL_SECONDS=$MIN_DWELL_SECONDS"

# CC_PASSWORD="${CC_PASSWORD:-}"
CC_PASSWORD="${CC_PASSWORD:-nctuiiot}"

if [[ -z "$CC_PASSWORD" ]]; then
  echo "請先 export CC_PASSWORD='你的 CoolerControl 密碼'"
  exit 1
fi

mkdir -p "$OUT_DIR"
export MPLCONFIGDIR="${MPLCONFIGDIR:-$HOME/.config/matplotlib}"
mkdir -p "$MPLCONFIGDIR"

cd "$AUTOSCALE_DIR"
source "$AUTOSCALE_DIR/iccl/bin/activate"

export VM_AGGREGATOR_MODULE=vm_aggregator
export MODE=fast
export DEBUG_OUTPUT=0
export NODE="$TARGET_NODE"
export K8S_NODE="$TARGET_NODE"
export NAMESPACE="$NAMESPACE_NAME"
export INTERVAL_SEC="$INTERVAL_SEC"
export OUT_DIR="$OUT_DIR"
export RUN_TAG="$RUN_ID"

python autoscale_api/scripts/record_stress_metrics.py > "$OUT_DIR/recorder.log" 2>&1 &
RECORDER_PID=$!

cleanup() {
  if ps -p "$RECORDER_PID" > /dev/null 2>&1; then
    kill "$RECORDER_PID" || true
    wait "$RECORDER_PID" || true
  fi

  :
}
trap cleanup EXIT

ssh ${SSH_OPTS} "${WORKER_SSH}" "
  cd ${WORKER_REPO} &&
  source ../gpu-tempctl-1080ti/bin/activate &&
  source fan_control_lab/env.sh &&
  source \$HOME/.cargo/env &&
  export CCTV_DAEMON_PASSWORD='${CC_PASSWORD}' &&
  export MPLCONFIGDIR=\$HOME/.config/matplotlib &&
  mkdir -p \$MPLCONFIGDIR &&
  python fan_control_lab/gpu_cycle_runner.py \
    --tag ${RUN_ID} \
    --target ${TARGET_C} \
    --band ${BAND} \
    --crit-temp 95 \
    --warmup-seconds ${WARMUP_SECONDS} \
    --normal-hold-seconds ${NORMAL_HOLD_SECONDS} \
    --fault-hold-seconds ${FAULT_HOLD_SECONDS} \
    --stable-seconds ${STABLE_SECONDS} \
    --sample-interval ${SAMPLE_INTERVAL} \
    --min-dwell-seconds ${MIN_DWELL_SECONDS} \
    --size 4096 \
    --duty 1.0 \
    --period-ms 100 \
    --baseline-mode GPU_DEFAULT \
    --fault-start-mode GPU_FAULT_5 \
    --restore-mode GPU_DEFAULT
" > "$OUT_DIR/worker_run.log" 2>&1 &
WORKER_PID=$!

mkdir -p "$OUT_DIR/worker_logs_live"

while kill -0 "$WORKER_PID" >/dev/null 2>&1; do
  rsync -e "ssh ${SSH_OPTS}" -av \
    "${WORKER_SSH}:${WORKER_REPO}/fan_control_lab/logs/${RUN_ID}/" \
    "$OUT_DIR/worker_logs_live/" >/dev/null 2>&1 || true

  python "$AUTOSCALE_DIR/experiments/thermal_analysis/live_cycle_plot.py" \
    --csv "$OUT_DIR/worker_logs_live/thermal.csv" \
    --out "$OUT_DIR/live_plot.png" \
    --target "$PLOT_TARGET_C" \
    --latency-glob "$LATENCY_GLOB" \
    --latency-root "${LATENCY_ROOT:-${RUN_DIR:-}}" \
    --band "$BAND" \
    --title "Live Thermal Curve - ${RUN_ID}" >/dev/null 2>&1 || true

  sleep 10
done

wait "$WORKER_PID"

kill "$RECORDER_PID" || true
wait "$RECORDER_PID" || true

mkdir -p "$OUT_DIR/worker_logs"

rsync -e "ssh ${SSH_OPTS}" -av \
  "${WORKER_SSH}:${WORKER_REPO}/fan_control_lab/logs/${RUN_ID}/" \
  "$OUT_DIR/worker_logs/"

python "$AUTOSCALE_DIR/experiments/thermal_analysis/live_cycle_plot.py" \
  --csv "$OUT_DIR/worker_logs/thermal.csv" \
  --out "$OUT_DIR/final_plot.png" \
  --target "$PLOT_TARGET_C" \
  --latency-glob "$LATENCY_GLOB" \
  --latency-root "${LATENCY_ROOT:-${RUN_DIR:-}}" \
  --band "$BAND" \
  --title "Final Thermal Curve - ${RUN_ID}" || true

python "$AUTOSCALE_DIR/experiments/thermal_analysis/merge_run.py" \
  --run-dir "$OUT_DIR"

echo
echo "完成：$OUT_DIR"
echo "請檢查："
echo "  1) $OUT_DIR/worker_logs/summary.json"
echo "  2) $OUT_DIR/aligned_summary.json"
echo "  3) $OUT_DIR/aligned_metrics.csv"

trap - EXIT
