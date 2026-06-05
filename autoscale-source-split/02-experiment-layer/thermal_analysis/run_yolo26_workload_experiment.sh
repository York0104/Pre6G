#!/usr/bin/env bash
set -euo pipefail

# One-shot wrapper for:
# 1) latency client start
# 2) thermal cycle execution
# 3) trim latency to aligned window
# 4) merge latency + thermal/system metrics
# 5) summarize service latency by phase
#
# Assumptions:
# - K8s YOLO26 service is already deployed and healthy
# - current repo exists on master
# - iccl venv exists at /home/icclz2/Pre6G/iccl (or VENV_ACTIVATE override)
# - run_cycle_from_master.sh, yolo26_latency_client.py,
#   trim_latency_to_aligned.py, merge_latency.py,
#   summarize_service_latency.py already exist
#
# Example:
#   export CC_PASSWORD='your_cc_password'
#   bash experiments/thermal_analysis/run_yolo26_workload_experiment.sh \
#     cycle90_yolo26n_workload_02

RUN_ID="${1:-cycle90_yolo26n_workload_$(date +%Y%m%d_%H%M%S)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_LAYER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPLIT_ROOT="$(cd "${EXPERIMENT_LAYER_DIR}/.." && pwd)"
PRE6G_ROOT="$(cd "${SPLIT_ROOT}/.." && pwd)"

CC_PASSWORD="${CC_PASSWORD:-}"

AUTOSCALE_DIR="${AUTOSCALE_DIR:-$EXPERIMENT_LAYER_DIR}"
VENV_ACTIVATE="${VENV_ACTIVATE:-$PRE6G_ROOT/iccl/bin/activate}"
RUN_DIR="${RUN_DIR:-$HOME/exp_runs/$RUN_ID}"

TARGET="${TARGET:-90}"
BAND="${BAND:-3}"
SERVICE_URL="${SERVICE_URL:-http://140.113.179.6:30026/infer}"
HEALTH_URL="${HEALTH_URL:-${SERVICE_URL%/infer}/healthz}"
IMAGE_PATH="${IMAGE_PATH:-$EXPERIMENT_LAYER_DIR/yolo26_workload/test_images/sanity_input.png}"
LATENCY_INTERVAL="${LATENCY_INTERVAL:-1.0}"
LATENCY_SECONDS="${LATENCY_SECONDS:-4200}"

if [[ -z "${CC_PASSWORD:-}" ]]; then
  echo "請先 export CC_PASSWORD='你的 CoolerControl 密碼'"
  exit 1
fi

if [[ ! -d "$AUTOSCALE_DIR" ]]; then
  echo "找不到 experiment-layer 目錄: $AUTOSCALE_DIR"
  exit 1
fi

if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "找不到 venv activate: $VENV_ACTIVATE"
  exit 1
fi

if [[ ! -f "$IMAGE_PATH" ]]; then
  echo "找不到測試圖片: $IMAGE_PATH"
  exit 1
fi

mkdir -p "$RUN_DIR"
cd "$AUTOSCALE_DIR"
source "$VENV_ACTIVATE"

for f in \
  thermal_analysis/run_cycle_from_master.sh \
  thermal_analysis/yolo26_latency_client.py \
  thermal_analysis/trim_latency_to_aligned.py \
  thermal_analysis/merge_latency.py \
  thermal_analysis/summarize_service_latency.py \
  thermal_analysis/plot_latency_results.py \
  thermal_analysis/plot_thermal_smclock_latency.py; do
  if [[ ! -f "$f" ]]; then
    echo "缺少必要檔案: $AUTOSCALE_DIR/$f"
    exit 1
  fi
done

echo "RUN_ID=$RUN_ID"
echo "RUN_DIR=$RUN_DIR"
echo "TARGET=$TARGET"
echo "BAND=$BAND"
echo "SERVICE_URL=$SERVICE_URL"
echo "IMAGE_PATH=$IMAGE_PATH"
echo "LATENCY_SECONDS=$LATENCY_SECONDS"

echo

echo "==> 檢查 YOLO26 service healthz"
curl -fsS "$HEALTH_URL" ; echo

echo "==> 背景啟動 latency client"
python "$AUTOSCALE_DIR/thermal_analysis/yolo26_latency_client.py" \
  --url "$SERVICE_URL" \
  --image "$IMAGE_PATH" \
  --out "$RUN_DIR/latency.csv" \
  --seconds "$LATENCY_SECONDS" \
  --interval "$LATENCY_INTERVAL" \
  > "$RUN_DIR/latency_client.log" 2>&1 &
LAT_PID=$!

cleanup() {
  if ps -p "$LAT_PID" >/dev/null 2>&1; then
    kill "$LAT_PID" >/dev/null 2>&1 || true
    wait "$LAT_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "==> 執行 thermal cycle"
OUT_DIR="$RUN_DIR" TARGET="$TARGET" BAND="$BAND" \
  bash "$AUTOSCALE_DIR/thermal_analysis/run_cycle_from_master.sh" "$RUN_ID"

echo "==> 停止 latency client"
cleanup

if [[ ! -f "$RUN_DIR/latency.csv" ]]; then
  echo "找不到 latency.csv: $RUN_DIR/latency.csv"
  exit 1
fi

if [[ ! -f "$RUN_DIR/aligned_metrics.csv" ]]; then
  echo "找不到 aligned_metrics.csv: $RUN_DIR/aligned_metrics.csv"
  exit 1
fi

echo "==> trim latency 到 aligned 範圍"
python "$AUTOSCALE_DIR/thermal_analysis/trim_latency_to_aligned.py" \
  --run-dir "$RUN_DIR" \
  | tee "$RUN_DIR/trim_latency.log"

cp "$RUN_DIR/latency.csv" "$RUN_DIR/latency_full_original.csv"
cp "$RUN_DIR/latency_trimmed.csv" "$RUN_DIR/latency.csv"

echo "==> merge latency + thermal/system"
python "$AUTOSCALE_DIR/thermal_analysis/merge_latency.py" \
  --run-dir "$RUN_DIR" \
  | tee "$RUN_DIR/merge_latency.log"

echo "==> summarize service latency"
python "$AUTOSCALE_DIR/thermal_analysis/summarize_service_latency.py" \
  --csv "$RUN_DIR/aligned_service_metrics.csv" \
  | tee "$RUN_DIR/service_latency_summary.csv"

echo "==> visualize latency results"
python "$AUTOSCALE_DIR/thermal_analysis/plot_latency_results.py" \
  --csv "$RUN_DIR/aligned_service_metrics.csv" \
  --outdir "$RUN_DIR/latency_plots"

echo "==> visualize thermal + fan + sm clock + latency"
python "$AUTOSCALE_DIR/thermal_analysis/plot_thermal_smclock_latency.py" \
  "$RUN_DIR" \
  --output "$RUN_DIR/thermal_smclock_latency.png" \
  --title "YOLO26 Thermal / Fan / SM Clock / Latency - ${RUN_ID}" \
  || true

echo
echo "==================== RUN SUMMARY ===================="
echo "RUN_DIR=$RUN_DIR"
echo

if [[ -f "$RUN_DIR/aligned_summary.json" ]]; then
  echo "---- aligned_summary.json ----"
  cat "$RUN_DIR/aligned_summary.json"
  echo
fi

if [[ -f "$RUN_DIR/service_latency_summary.csv" ]]; then
  echo "---- service_latency_summary.csv ----"
  cat "$RUN_DIR/service_latency_summary.csv"
  echo
fi

if [[ -f "$RUN_DIR/trim_latency.log" ]]; then
  echo "---- trim_latency.log (tail -n 20) ----"
  tail -n 20 "$RUN_DIR/trim_latency.log"
  echo
fi

if [[ -f "$RUN_DIR/merge_latency.log" ]]; then
  echo "---- merge_latency.log (tail -n 20) ----"
  tail -n 20 "$RUN_DIR/merge_latency.log"
  echo
fi

if [[ -f "$RUN_DIR/worker_logs/summary.json" ]]; then
  echo "---- worker_logs/summary.json ----"
  cat "$RUN_DIR/worker_logs/summary.json"
  echo
fi

if [[ -f "$RUN_DIR/thermal_smclock_latency.png" ]]; then
  echo "---- thermal_smclock_latency.png ----"
  echo "$RUN_DIR/thermal_smclock_latency.png"
  echo
fi

echo "====================================================="
echo "完成：$RUN_DIR"

trap - EXIT
