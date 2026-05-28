#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-intent-lab}"
NODE_NAME="${NODE_NAME:-icclz1}"
NODE_SSH_ALIAS="${NODE_SSH_ALIAS:-icclz1-gpu}"
NODE_SSH="${NODE_SSH:-$NODE_SSH_ALIAS}"
FOCUS_DEPLOY="${FOCUS_DEPLOY:-yolo26n-focus}"
BG_DEPLOY_1="${BG_DEPLOY_1:-yolo26n-bg-1}"
TARGET_MODE="${TARGET_MODE:-service}"
VM_URL="${VM_URL:-http://140.113.179.9:31888}"
NETDATA_URL="${NETDATA_URL:-http://140.113.179.9:32163}"
NETDATA_CHILD_URL="${NETDATA_CHILD_URL:-$NETDATA_URL}"
NETDATA_PARENT_BASE_URL="${NETDATA_PARENT_BASE_URL:-$NETDATA_URL}"

TIMEOUT_SEC="${TIMEOUT_SEC:-30}"
REPEAT="${REPEAT:-10}"
MEAS_SVC_NAME="${MEAS_SVC_NAME:-}"

WARMUP_SECONDS="${WARMUP_SECONDS:-0}"
NORMAL_HOLD_SECONDS="${NORMAL_HOLD_SECONDS:-0}"
FAULT_HOLD_SECONDS="${FAULT_HOLD_SECONDS:-1800}"
FAULT_START_MODE="${FAULT_START_MODE:-GPU_FAULT_5}"
BASELINE_MODE="${BASELINE_MODE:-GPU_DEFAULT}"
RESTORE_MODE="${RESTORE_MODE:-GPU_DEFAULT}"
TARGET_TEMP_C="${TARGET_TEMP_C:-90}"
BAND="${BAND:-3}"
CC_PASSWORD="${CC_PASSWORD:-nctuiiot}"
THERMAL_CONTROL_MODE="${THERMAL_CONTROL_MODE:-fixed_manual}"
FIXED_FAN_PCT="${FIXED_FAN_PCT:-5}"

CLIENT_DURATION="${CLIENT_DURATION:-$((WARMUP_SECONDS + NORMAL_HOLD_SECONDS + FAULT_HOLD_SECONDS))}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPERIMENT_LAYER_DIR="$(cd "${BASE_DIR}/.." && pwd)"
SPLIT_ROOT="$(cd "${EXPERIMENT_LAYER_DIR}/.." && pwd)"
MONITORING_DIR="${SPLIT_ROOT}/01-monitoring-layer"
PRE6G_ROOT="$(cd "${SPLIT_ROOT}/.." && pwd)"
VENV_ACTIVATE="${PRE6G_ROOT}/iccl/bin/activate"
CLIENT="${BASE_DIR}/common/request_client_serial.py"
THERMAL_RUNNER="${BASE_DIR}/common/run_thermal_cycle_from_master.sh"
THERMAL_ANALYZER="${BASE_DIR}/common/analyze_single_pod_serial_fault_fan.py"
THERMAL_PLOTTER="${BASE_DIR}/common/plot_single_pod_serial_fault_fan.py"
TIMELINE_PLOTTER="${BASE_DIR}/common/plot_task3_full_timeline.py"
RESOURCE_PLOTTER="${BASE_DIR}/common/plot_resource_overview.py"
VM_AGG_COLLECTOR="${BASE_DIR}/../thermal_analysis/collect_vm_aggregator_csv.py"
VM_AGG_TRAINING="${BASE_DIR}/common/extract_vmagg_training_features.py"
VM_AGGREGATOR="${MONITORING_DIR}/vm_aggregator.py"
IMG="${EXPERIMENT_LAYER_DIR}/yolo26_k8s/test_images/sanity_input.png"
VM_AGG_INTERVAL="${VM_AGG_INTERVAL:-1.0}"

RESULT_ROOT="${BASE_DIR}/results/single_pod_serial_fault_fan"
RUN_ID="singlepod_serial_faultfan_repeat${REPEAT}_${FAULT_HOLD_SECONDS}s_$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${RESULT_ROOT}/${RUN_ID}"
THERMAL_DIR="${RUN_DIR}/thermal_cycle"
mkdir -p "${RESULT_ROOT}" "${RUN_DIR}" "${THERMAL_DIR}"

echo "[INFO] RUN_DIR=${RUN_DIR}"
echo "[INFO] THERMAL_DIR=${THERMAL_DIR}"

cd "${BASE_DIR}"

if [ -f "${VENV_ACTIVATE}" ]; then
  # shellcheck disable=SC1091
  source "${VENV_ACTIVATE}"
fi

echo "[INFO] enforce single-pod mode: focus=1, background=0"
kubectl -n "${NAMESPACE}" scale "deploy/${FOCUS_DEPLOY}" --replicas=1
kubectl -n "${NAMESPACE}" scale "deploy/${BG_DEPLOY_1}" --replicas=0
kubectl -n "${NAMESPACE}" rollout status "deploy/${FOCUS_DEPLOY}"

kubectl -n "${NAMESPACE}" get "deploy/${FOCUS_DEPLOY}" \
  -o custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas \
  | tee "${RUN_DIR}/deploy_before.txt"
kubectl -n "${NAMESPACE}" get pods -l app=yolo26n -o wide | tee "${RUN_DIR}/pods_before.txt"
kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp | tail -n 50 | tee "${RUN_DIR}/events_before.txt"

FOCUS_POD="$(kubectl -n "${NAMESPACE}" get pod -l app=yolo26n,role=focus -o jsonpath='{.items[0].metadata.name}')"
FOCUS_IP="$(kubectl -n "${NAMESPACE}" get pod -l app=yolo26n,role=focus -o jsonpath='{.items[0].status.podIP}')"
MEAS_SVC_IP="$(kubectl -n "${NAMESPACE}" get svc "${MEAS_SVC_NAME}" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)"

if [ "${TARGET_MODE}" = "service" ] && [ -n "${MEAS_SVC_IP}" ]; then
  TARGET_URL="http://${MEAS_SVC_IP}:18080/infer?repeat=${REPEAT}"
else
  TARGET_MODE="pod"
  TARGET_URL="http://${FOCUS_IP}:18080/infer?repeat=${REPEAT}"
fi

{
  echo "RUN_ID=${RUN_ID}"
  echo "RUN_DIR=${RUN_DIR}"
  echo "THERMAL_DIR=${THERMAL_DIR}"
  echo "NAMESPACE=${NAMESPACE}"
  echo "FOCUS_DEPLOY=${FOCUS_DEPLOY}"
  echo "BG_DEPLOY_1=${BG_DEPLOY_1}"
  echo "FOCUS_POD=${FOCUS_POD}"
  echo "FOCUS_IP=${FOCUS_IP}"
  echo "MEAS_SVC_NAME=${MEAS_SVC_NAME}"
  echo "MEAS_SVC_IP=${MEAS_SVC_IP}"
  echo "TARGET_MODE=${TARGET_MODE}"
  echo "TARGET_URL=${TARGET_URL}"
  echo "TIMEOUT_SEC=${TIMEOUT_SEC}"
  echo "REPEAT=${REPEAT}"
  echo "CLIENT_DURATION=${CLIENT_DURATION}"
  echo "THERMAL_CONTROL_MODE=${THERMAL_CONTROL_MODE}"
  echo "FIXED_FAN_PCT=${FIXED_FAN_PCT}"
  echo "WARMUP_SECONDS=${WARMUP_SECONDS}"
  echo "NORMAL_HOLD_SECONDS=${NORMAL_HOLD_SECONDS}"
  echo "FAULT_HOLD_SECONDS=${FAULT_HOLD_SECONDS}"
  echo "FAULT_START_MODE=${FAULT_START_MODE}"
  echo "BASELINE_MODE=${BASELINE_MODE}"
  echo "RESTORE_MODE=${RESTORE_MODE}"
  echo "TARGET_TEMP_C=${TARGET_TEMP_C}"
  echo "BAND=${BAND}"
  echo "CLIENT_MODE=closed_loop_serial"
  echo "VM_URL=${VM_URL}"
  echo "NETDATA_URL=${NETDATA_URL}"
  echo "NETDATA_CHILD_URL=${NETDATA_CHILD_URL}"
  echo "NETDATA_PARENT_BASE_URL=${NETDATA_PARENT_BASE_URL}"
} | tee "${RUN_DIR}/experiment_config.txt"

echo "[INFO] Testing focus health..."
curl -s "http://${FOCUS_IP}:18080/healthz" | tee "${RUN_DIR}/focus_health_before.json"
echo ""

if [ -n "${MEAS_SVC_IP}" ]; then
  echo "[INFO] Testing service health..."
  curl -s "http://${MEAS_SVC_IP}:18080/healthz" | tee "${RUN_DIR}/service_health_before.json"
  echo ""
fi

echo "[INFO] Starting nvidia-smi GPU monitor..."
ssh "${NODE_SSH}" \
  "nvidia-smi --query-gpu=timestamp,index,name,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm,clocks.mem --format=csv -l 1" \
  > "${RUN_DIR}/nvidia_smi_gpu_1s.csv" 2> "${RUN_DIR}/nvidia_smi_gpu_1s.err" &
GPU_PID=$!

echo "[INFO] Starting kubectl top monitor..."
(
  while true; do
    echo "timestamp,$(date -Is)"
    echo "[node]"
    kubectl top node "${NODE_NAME}" --no-headers || true
    echo "[pods]"
    kubectl -n "${NAMESPACE}" top pod -l app=yolo26n --no-headers || true
    echo "----"
    sleep 1
  done
) > "${RUN_DIR}/kubectl_top_1s.log" 2>&1 &
TOP_PID=$!

cleanup() {
  kill "${GPU_PID}" "${TOP_PID}" "${THERMAL_PID:-}" "${CLIENT_PID:-}" "${VM_AGG_PID:-}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

START_EPOCH="$(date +%s)"
START_ISO="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "START_EPOCH=${START_EPOCH}" | tee "${RUN_DIR}/time_window.txt"
echo "START_ISO=${START_ISO}" | tee -a "${RUN_DIR}/time_window.txt"

echo "[INFO] Start vm_aggregator collector..."
python3 "${VM_AGG_COLLECTOR}" \
  --aggregator "${VM_AGGREGATOR}" \
  --out "${RUN_DIR}/vm_aggregator_timeseries.csv" \
  --seconds "${CLIENT_DURATION}" \
  --interval "${VM_AGG_INTERVAL}" \
  --node "${NODE_NAME}" \
  --namespace "${NAMESPACE}" \
  --vm-url "${VM_URL}" \
  --netdata-url "${NETDATA_URL}" \
  --netdata-child-url "${NETDATA_CHILD_URL}" \
  --netdata-parent-base-url "${NETDATA_PARENT_BASE_URL}" \
  --mode fast \
  > "${RUN_DIR}/vm_aggregator_timeseries.log" 2>&1 &
VM_AGG_PID=$!

echo "[INFO] Start serial client"
python3 "${CLIENT}" \
  --role measurement \
  --url "${TARGET_URL}" \
  --image "${IMG}" \
  --duration "${CLIENT_DURATION}" \
  --timeout "${TIMEOUT_SEC}" \
  --output "${RUN_DIR}/measurement_raw.csv" \
  > "${RUN_DIR}/measurement.log" 2>&1 &
CLIENT_PID=$!

echo "[INFO] Start thermal runner"
OUT_DIR="${THERMAL_DIR}" \
TARGET_TEMP_C="${TARGET_TEMP_C}" \
BAND="${BAND}" \
WARMUP_SECONDS="${WARMUP_SECONDS}" \
NORMAL_HOLD_SECONDS="${NORMAL_HOLD_SECONDS}" \
FAULT_HOLD_SECONDS="${FAULT_HOLD_SECONDS}" \
FAULT_START_MODE="${FAULT_START_MODE}" \
BASELINE_MODE="${BASELINE_MODE}" \
RESTORE_MODE="${RESTORE_MODE}" \
CC_PASSWORD="${CC_PASSWORD}" \
THERMAL_CONTROL_MODE="${THERMAL_CONTROL_MODE}" \
FIXED_FAN_PCT="${FIXED_FAN_PCT}" \
bash "${THERMAL_RUNNER}" "${RUN_ID}" > "${RUN_DIR}/thermal_runner.log" 2>&1 &
THERMAL_PID=$!

wait "${THERMAL_PID}"
wait "${CLIENT_PID}"

END_EPOCH="$(date +%s)"
END_ISO="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "END_EPOCH=${END_EPOCH}" | tee -a "${RUN_DIR}/time_window.txt"
echo "END_ISO=${END_ISO}" | tee -a "${RUN_DIR}/time_window.txt"

kill "${GPU_PID}" "${TOP_PID}" 2>/dev/null || true
kill "${VM_AGG_PID}" 2>/dev/null || true
wait "${VM_AGG_PID}" || true
sleep 2

kubectl -n "${NAMESPACE}" get pods -l app=yolo26n -o wide | tee "${RUN_DIR}/pods_after.txt"
kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp | tail -n 50 | tee "${RUN_DIR}/events_after.txt"

echo "[INFO] Extract vm_aggregator training-ready features..."
python3 "${VM_AGG_TRAINING}" \
  --input "${RUN_DIR}/vm_aggregator_timeseries.csv" \
  > "${RUN_DIR}/vm_aggregator_training_features.log" 2>&1 || true

python3 - "${RUN_DIR}" <<'PY' | tee "${RUN_DIR}/summary.txt"
import csv
import math
import statistics
import sys
from collections import Counter
from pathlib import Path


def to_float(value):
    if value in (None, ""):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num):
        return None
    return num


def percentile(values, pct):
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    pos = (len(values) - 1) * pct
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return values[int(pos)]
    weight = pos - lower
    return values[lower] * (1 - weight) + values[upper] * weight


run_dir = Path(sys.argv[1])
path = run_dir / "measurement_raw.csv"
with path.open(newline="") as fh:
    rows = list(csv.DictReader(fh))

clean = [row for row in rows if (row.get("error_type") or "") == "normal_success"]
success_values = []
for row in rows:
    value = row.get("success", "")
    if str(value).strip().lower() in {"1", "1.0", "true"}:
        success_values.append(1.0)
    elif str(value).strip().lower() in {"0", "0.0", "false"}:
        success_values.append(0.0)

print("rows:", len(rows))
print("success rate:", (sum(success_values) / len(success_values)) if success_values else None)
print("\nerror types:")
for key, count in Counter((row.get("error_type") or "") for row in rows).items():
    label = key if key else "<empty>"
    print(f"{label}: {count}")

for col in ["e2e_latency_ms", "server_latency_ms", "server_total_latency_ms"]:
    values = [to_float(row.get(col)) for row in clean]
    values = [v for v in values if v is not None]
    if values:
        print(f"\nclean {col}:")
        print(f"count: {len(values)}")
        print(f"mean: {statistics.fmean(values):.6f}")
        print(f"min: {min(values):.6f}")
        print(f"p50: {percentile(values, 0.50):.6f}")
        print(f"p90: {percentile(values, 0.90):.6f}")
        print(f"p95: {percentile(values, 0.95):.6f}")
        print(f"p99: {percentile(values, 0.99):.6f}")
        print(f"max: {max(values):.6f}")

vm_path = run_dir / "vm_aggregator_timeseries.csv"
if vm_path.exists():
    print(f"\nvm_aggregator_timeseries_csv: {vm_path}")
train_path = run_dir / "vm_aggregator_training_features.csv"
if train_path.exists():
    print(f"vm_aggregator_training_features_csv: {train_path}")
PY

python3 "${THERMAL_ANALYZER}" "${RUN_DIR}" | tee "${RUN_DIR}/fault_fan_analysis.txt" || true
python3 "${THERMAL_PLOTTER}" "${RUN_DIR}" > "${RUN_DIR}/plot_fault_fan.log" 2>&1 || true
python3 "${TIMELINE_PLOTTER}" "${RUN_DIR}" > "${RUN_DIR}/plot_full_timeline.log" 2>&1 || true
python3 "${RESOURCE_PLOTTER}" "${RUN_DIR}" > "${RUN_DIR}/plot_resource_overview.log" 2>&1 || true

echo "[INFO] Done"
echo "[INFO] Result directory: ${RUN_DIR}"
