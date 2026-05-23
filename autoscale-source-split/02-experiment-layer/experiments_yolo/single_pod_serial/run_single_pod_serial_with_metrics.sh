#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-intent-lab}"
NODE_NAME="${NODE_NAME:-icclz1}"
NODE_SSH="${NODE_SSH:-icclz1@100.105.48.97}"
FOCUS_DEPLOY="${FOCUS_DEPLOY:-yolo26n-task3-focus}"
BG_DEPLOY_1="${BG_DEPLOY_1:-yolo26n-task3-bg}"
BG_DEPLOY_2="${BG_DEPLOY_2:-}"
TARGET_MODE="${TARGET_MODE:-service}"
VM_URL="${VM_URL:-http://100.68.32.118:31888}"
NETDATA_URL="${NETDATA_URL:-http://100.68.32.118:32163}"
NETDATA_CHILD_URL="${NETDATA_CHILD_URL:-$NETDATA_URL}"
NETDATA_PARENT_BASE_URL="${NETDATA_PARENT_BASE_URL:-$NETDATA_URL}"

DURATION="${DURATION:-1800}"
TIMEOUT_SEC="${TIMEOUT_SEC:-20}"
REPEAT="${REPEAT:-1}"
MEAS_SVC_NAME="${MEAS_SVC_NAME:-yolo26n-task3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPERIMENT_LAYER_DIR="$(cd "${BASE_DIR}/.." && pwd)"
SPLIT_ROOT="$(cd "${EXPERIMENT_LAYER_DIR}/.." && pwd)"
MONITORING_DIR="${SPLIT_ROOT}/01-monitoring-layer"
CLIENT="${BASE_DIR}/common/request_client_serial.py"
SERIAL_ANALYZER="${BASE_DIR}/common/analyze_single_pod_serial.py"
TIMELINE_PLOTTER="${BASE_DIR}/common/plot_task3_full_timeline.py"
RESOURCE_PLOTTER="${BASE_DIR}/common/plot_resource_overview.py"
VM_AGG_COLLECTOR="${BASE_DIR}/../thermal_analysis/collect_vm_aggregator_csv.py"
VM_AGG_TRAINING="${BASE_DIR}/common/extract_vmagg_training_features.py"
VM_AGGREGATOR="${MONITORING_DIR}/vm_aggregator.py"
IMG="${EXPERIMENT_LAYER_DIR}/yolo26_k8s/test_images/sanity_input.png"
VM_AGG_INTERVAL="${VM_AGG_INTERVAL:-1.0}"

RESULT_ROOT="${BASE_DIR}/results/single_pod_serial"
RUN_ID="singlepod_serial_repeat${REPEAT}_${DURATION}s_$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${RESULT_ROOT}/${RUN_ID}"
mkdir -p "${RESULT_ROOT}" "${RUN_DIR}"

echo "[INFO] RUN_DIR=${RUN_DIR}"

cd "${BASE_DIR}"

if [ -f ~/AutoScale/iccl/bin/activate ]; then
  # shellcheck disable=SC1091
  source ~/AutoScale/iccl/bin/activate
fi

echo "[INFO] Scale deployments for single-pod serial experiment"
kubectl -n "${NAMESPACE}" scale "deploy/${FOCUS_DEPLOY}" --replicas=1
kubectl -n "${NAMESPACE}" scale "deploy/${BG_DEPLOY_1}" --replicas=0
if [ -n "${BG_DEPLOY_2}" ]; then
  kubectl -n "${NAMESPACE}" scale "deploy/${BG_DEPLOY_2}" --replicas=0
fi

kubectl -n "${NAMESPACE}" rollout status "deploy/${FOCUS_DEPLOY}"

echo "[INFO] Wait until background pods disappear"
for dep in "${BG_DEPLOY_1}" "${BG_DEPLOY_2}"; do
  if [ -z "${dep}" ]; then
    continue
  fi
  for _ in $(seq 1 60); do
    count="$(kubectl -n "${NAMESPACE}" get pods -l "app=yolo26n" --field-selector=status.phase=Running --no-headers 2>/dev/null | grep -c "${dep}" || true)"
    if [ "${count}" = "0" ]; then
      break
    fi
    sleep 1
  done
done

{
  kubectl -n "${NAMESPACE}" get "deploy/${FOCUS_DEPLOY}" \
    -o custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas
  kubectl -n "${NAMESPACE}" get "deploy/${BG_DEPLOY_1}" \
    -o custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas
  if [ -n "${BG_DEPLOY_2}" ]; then
    kubectl -n "${NAMESPACE}" get "deploy/${BG_DEPLOY_2}" \
      -o custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas
  fi
} | tee "${RUN_DIR}/deploy_before.txt"
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
  echo "NAMESPACE=${NAMESPACE}"
  echo "NODE_NAME=${NODE_NAME}"
  echo "FOCUS_DEPLOY=${FOCUS_DEPLOY}"
  echo "FOCUS_POD=${FOCUS_POD}"
  echo "FOCUS_IP=${FOCUS_IP}"
  echo "MEAS_SVC_NAME=${MEAS_SVC_NAME}"
  echo "MEAS_SVC_IP=${MEAS_SVC_IP}"
  echo "TARGET_MODE=${TARGET_MODE}"
  echo "TARGET_URL=${TARGET_URL}"
  echo "DURATION=${DURATION}"
  echo "TIMEOUT_SEC=${TIMEOUT_SEC}"
  echo "REPEAT=${REPEAT}"
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
  kill "${GPU_PID}" "${TOP_PID}" "${VM_AGG_PID:-}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 3

START_EPOCH="$(date +%s)"
START_ISO="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "START_EPOCH=${START_EPOCH}" | tee "${RUN_DIR}/time_window.txt"
echo "START_ISO=${START_ISO}" | tee -a "${RUN_DIR}/time_window.txt"

echo "[INFO] Start vm_aggregator collector..."
python3 "${VM_AGG_COLLECTOR}" \
  --aggregator "${VM_AGGREGATOR}" \
  --out "${RUN_DIR}/vm_aggregator_timeseries.csv" \
  --seconds "${DURATION}" \
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

echo "[INFO] Starting serial measurement client"
python3 "${CLIENT}" \
  --role measurement \
  --url "${TARGET_URL}" \
  --image "${IMG}" \
  --duration "${DURATION}" \
  --timeout "${TIMEOUT_SEC}" \
  --output "${RUN_DIR}/measurement_raw.csv" \
  > "${RUN_DIR}/measurement.log" 2>&1

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

echo "[INFO] Quick summary..."
python3 - "${RUN_DIR}" <<'PY' | tee "${RUN_DIR}/summary.txt"
import sys
from pathlib import Path
import pandas as pd

run_dir = Path(sys.argv[1])
path = run_dir / "measurement_raw.csv"
df = pd.read_csv(path)
clean = df[df["error_type"].fillna("") == "normal_success"].copy()

print("rows:", len(df))
print("success rate:", df["success"].mean() if len(df) else None)
print("\nerror types:")
print(df["error_type"].value_counts(dropna=False))

for col in ["e2e_latency_ms", "server_latency_ms", "server_total_latency_ms"]:
    if col in clean.columns:
        clean[col] = pd.to_numeric(clean[col], errors="coerce")
        print(f"\nclean {col}:")
        print(clean[col].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

print("\npods:")
print(df["server_pod_name"].value_counts(dropna=False))

if "inter_request_gap_ms" in df.columns:
    s = pd.to_numeric(df["inter_request_gap_ms"], errors="coerce").dropna()
    if len(s):
        print("\ninter_request_gap_ms:")
        print(s.describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

vm_path = run_dir / "vm_aggregator_timeseries.csv"
if vm_path.exists():
    print(f"\nvm_aggregator_timeseries_csv: {vm_path}")
train_path = run_dir / "vm_aggregator_training_features.csv"
if train_path.exists():
    print(f"vm_aggregator_training_features_csv: {train_path}")
PY

echo "[INFO] Serial analysis..."
python3 "${SERIAL_ANALYZER}" "${RUN_DIR}" | tee -a "${RUN_DIR}/serial_analysis.txt"

echo "[INFO] Plot full timeline..."
python3 "${TIMELINE_PLOTTER}" "${RUN_DIR}" > "${RUN_DIR}/plot_full_timeline.log" 2>&1 || true

echo "[INFO] Plot GPU resource overview..."
python3 "${RESOURCE_PLOTTER}" "${RUN_DIR}" > "${RUN_DIR}/plot_resource_overview.log" 2>&1 || true

echo "[INFO] Done"
echo "[INFO] Result directory: ${RUN_DIR}"
