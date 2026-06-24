#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-intent-lab}"
APP="${APP:-yolo26n}"
EXP="${EXP:-single-gpu-bound}"
GPU_NODE_NAME="${GPU_NODE_NAME:?missing GPU_NODE_NAME, e.g. iccl-s3-251230}"
NODE_SSH="${NODE_SSH:?missing NODE_SSH, e.g. mirc516@100.90.127.1}"

DURATION="${DURATION:-300}"
MEAS_CONCURRENCY="${MEAS_CONCURRENCY:-32}"
MEAS_INTERVAL="${MEAS_INTERVAL:-1.0}"
TIMEOUT_SEC="${TIMEOUT_SEC:-20}"
REPEAT="${REPEAT:-1}"
MEAS_SVC_NAME="${MEAS_SVC_NAME:-yolo26n-single-gpu}"
YOLO_MODEL="${YOLO_MODEL:-${MODEL_NAME:-yolo26m.pt}}"
YOLO_IMGSZ="${YOLO_IMGSZ:-${IMG_SIZE:-640}}"
REQUEST_IMAGE="${REQUEST_IMAGE:-}"
INFER_QUERY_EXTRA="${INFER_QUERY_EXTRA:-}"
BATCH_SIZE="${BATCH_SIZE:-1}"
WARMUP_BATCH="${WARMUP_BATCH:-${BATCH_SIZE}}"
CPU_REQUEST="${CPU_REQUEST:-1000m}"
CPU_LIMIT="${CPU_LIMIT:-2000m}"
MEMORY_REQUEST="${MEMORY_REQUEST:-4Gi}"
MEMORY_LIMIT="${MEMORY_LIMIT:-6Gi}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-300s}"
IMAGE_REF="${IMAGE_REF:-local/yolo26n:0.1}"
IMAGE_PULL_POLICY="${IMAGE_PULL_POLICY:-IfNotPresent}"
IMAGE_PULL_SECRET="${IMAGE_PULL_SECRET:-}"
VM_URL="${VM_URL:-http://140.113.179.9:31888}"
NETDATA_URL="${NETDATA_URL:-http://140.113.179.9:32163}"
NETDATA_CHILD_URL="${NETDATA_CHILD_URL:-$NETDATA_URL}"
NETDATA_PARENT_BASE_URL="${NETDATA_PARENT_BASE_URL:-$NETDATA_URL}"
VM_AGG_INTERVAL="${VM_AGG_INTERVAL:-1.0}"
CLEANUP_ON_EXIT="${CLEANUP_ON_EXIT:-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPERIMENT_LAYER_DIR="$(cd "${BASE_DIR}/.." && pwd)"
SPLIT_ROOT="$(cd "${EXPERIMENT_LAYER_DIR}/.." && pwd)"
MONITORING_DIR="${SPLIT_ROOT}/01-monitoring-layer"
CLIENT="${BASE_DIR}/common/request_client_parallel.py"
RESOURCE_PLOTTER="${BASE_DIR}/common/plot_resource_overview.py"
TIMELINE_PLOTTER="${BASE_DIR}/common/plot_task3_full_timeline.py"
VM_AGG_COLLECTOR="${BASE_DIR}/../thermal_analysis/collect_vm_aggregator_csv.py"
VM_AGG_TRAINING="${BASE_DIR}/common/extract_vmagg_training_features.py"
VM_AGGREGATOR="${MONITORING_DIR}/vm_aggregator.py"
DEFAULT_IMG="${EXPERIMENT_LAYER_DIR}/yolo26_workload/test_images/sanity_input.png"
IMG="${REQUEST_IMAGE:-${DEFAULT_IMG}}"

RESULT_ROOT="${BASE_DIR}/results/single_pod_gpu_bound"
MODEL_SLUG="$(printf '%s' "${YOLO_MODEL}" | tr '/:.' '_' | tr -cd '[:alnum:]_-')"
RUN_ID="single_gpu_${GPU_NODE_NAME}_${MODEL_SLUG}_img${YOLO_IMGSZ}_c${MEAS_CONCURRENCY}_r${REPEAT}_${DURATION}s_$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${RESULT_ROOT}/${RUN_ID}"
STACK_RENDERED="/tmp/${RUN_ID}.yaml"
mkdir -p "${RESULT_ROOT}" "${RUN_DIR}"

PRE6G_ROOT="$(cd "${SPLIT_ROOT}/.." && pwd)"
VENV_ACTIVATE="${PRE6G_ROOT}/iccl/bin/activate"
if [ -f "${VENV_ACTIVATE}" ]; then
  # shellcheck disable=SC1091
  source "${VENV_ACTIVATE}"
fi

log_info() {
  echo "[INFO] $*"
}

log_error() {
  echo "[ERROR] $*" >&2
}

if [ ! -f "${IMG}" ]; then
  log_error "Request image not found: ${IMG}"
  exit 2
fi

cleanup() {
  kill "${GPU_PID:-}" "${TOP_PID:-}" "${VM_AGG_PID:-}" >/dev/null 2>&1 || true
  if [ "${CLEANUP_ON_EXIT}" = "1" ]; then
    kubectl delete -f "${STACK_RENDERED}" --ignore-not-found >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

render_stack() {
  cat > "${STACK_RENDERED}" <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${APP}-${EXP}
  namespace: ${NAMESPACE}
  labels:
    app: ${APP}
    exp: ${EXP}
    role: focus
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: ${APP}
      exp: ${EXP}
      role: focus
  template:
    metadata:
      labels:
        app: ${APP}
        exp: ${EXP}
        role: focus
    spec:
      runtimeClassName: nvidia
EOF

  if [ -n "${IMAGE_PULL_SECRET}" ]; then
    cat >> "${STACK_RENDERED}" <<EOF
      imagePullSecrets:
        - name: ${IMAGE_PULL_SECRET}
EOF
  fi

  cat >> "${STACK_RENDERED}" <<EOF
      nodeSelector:
        kubernetes.io/hostname: ${GPU_NODE_NAME}
      containers:
        - name: yolo26
          image: ${IMAGE_REF}
          imagePullPolicy: ${IMAGE_PULL_POLICY}
          ports:
            - containerPort: 18080
          env:
            - name: YOLO26_SERVICE_ROLE
              value: "focus"
            - name: YOLO_MODEL
              value: "${YOLO_MODEL}"
            - name: YOLO26_MODEL
              value: "${YOLO_MODEL}"
            - name: YOLO26_DEVICE
              value: "cuda:0"
            - name: YOLO_IMGSZ
              value: "${YOLO_IMGSZ}"
            - name: YOLO26_IMGSZ
              value: "${YOLO_IMGSZ}"
            - name: YOLO26_WARMUP_BATCH
              value: "${WARMUP_BATCH}"
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
          resources:
            requests:
              cpu: "${CPU_REQUEST}"
              memory: "${MEMORY_REQUEST}"
              nvidia.com/gpu: "1"
            limits:
              cpu: "${CPU_LIMIT}"
              memory: "${MEMORY_LIMIT}"
              nvidia.com/gpu: "1"
          readinessProbe:
            httpGet:
              path: /healthz
              port: 18080
            initialDelaySeconds: 30
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /healthz
              port: 18080
            initialDelaySeconds: 60
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: ${MEAS_SVC_NAME}
  namespace: ${NAMESPACE}
  labels:
    app: ${APP}
    exp: ${EXP}
spec:
  type: ClusterIP
  selector:
    app: ${APP}
    exp: ${EXP}
    role: focus
  ports:
    - name: http
      port: 18080
      targetPort: 18080
EOF
}

log_info "RUN_DIR=${RUN_DIR}"
log_info "Checking target node ${GPU_NODE_NAME}..."
kubectl get node "${GPU_NODE_NAME}" -o wide

log_info "Rendering single-pod full-GPU stack..."
render_stack

log_info "Applying stack..."
kubectl apply -f "${STACK_RENDERED}"

log_info "Waiting for deployment rollout..."
kubectl -n "${NAMESPACE}" rollout status "deploy/${APP}-${EXP}" --timeout="${ROLLOUT_TIMEOUT}"

POD_NAME="$(kubectl -n "${NAMESPACE}" get pod -l app="${APP}",exp="${EXP}",role=focus --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')"
POD_IP="$(kubectl -n "${NAMESPACE}" get pod -l app="${APP}",exp="${EXP}",role=focus --field-selector=status.phase=Running -o jsonpath='{.items[0].status.podIP}')"
MEAS_SVC_IP="$(kubectl -n "${NAMESPACE}" get svc "${MEAS_SVC_NAME}" -o jsonpath='{.spec.clusterIP}')"

if [ -z "${POD_NAME}" ] || [ -z "${POD_IP}" ] || [ -z "${MEAS_SVC_IP}" ]; then
  log_error "Pod or service not ready."
  kubectl -n "${NAMESPACE}" get pods -l app="${APP}",exp="${EXP}" -o wide || true
  kubectl -n "${NAMESPACE}" get svc "${MEAS_SVC_NAME}" -o wide || true
  exit 2
fi

INFER_URL="http://${MEAS_SVC_IP}:18080/infer?repeat=${REPEAT}&batch=${BATCH_SIZE}"
if [ -n "${INFER_QUERY_EXTRA}" ]; then
  INFER_URL="${INFER_URL}&${INFER_QUERY_EXTRA}"
fi

{
  echo "RUN_ID=${RUN_ID}"
  echo "RUN_DIR=${RUN_DIR}"
  echo "NAMESPACE=${NAMESPACE}"
  echo "APP=${APP}"
  echo "EXP=${EXP}"
  echo "GPU_NODE_NAME=${GPU_NODE_NAME}"
  echo "NODE_SSH=${NODE_SSH}"
  echo "POD_NAME=${POD_NAME}"
  echo "POD_IP=${POD_IP}"
  echo "MEAS_SVC_NAME=${MEAS_SVC_NAME}"
  echo "MEAS_SVC_IP=${MEAS_SVC_IP}"
  echo "INFER_URL=${INFER_URL}"
  echo "YOLO_MODEL=${YOLO_MODEL}"
  echo "YOLO_IMGSZ=${YOLO_IMGSZ}"
  echo "REQUEST_IMAGE=${IMG}"
  echo "BATCH_SIZE=${BATCH_SIZE}"
  echo "WARMUP_BATCH=${WARMUP_BATCH}"
  echo "DURATION=${DURATION}"
  echo "MEAS_CONCURRENCY=${MEAS_CONCURRENCY}"
  echo "REPEAT=${REPEAT}"
  echo "MEAS_INTERVAL=${MEAS_INTERVAL}"
  echo "TIMEOUT_SEC=${TIMEOUT_SEC}"
  echo "CPU_REQUEST=${CPU_REQUEST}"
  echo "CPU_LIMIT=${CPU_LIMIT}"
  echo "MEMORY_REQUEST=${MEMORY_REQUEST}"
  echo "MEMORY_LIMIT=${MEMORY_LIMIT}"
  echo "ROLLOUT_TIMEOUT=${ROLLOUT_TIMEOUT}"
  echo "VM_URL=${VM_URL}"
  echo "NETDATA_URL=${NETDATA_URL}"
  echo "NETDATA_CHILD_URL=${NETDATA_CHILD_URL}"
  echo "NETDATA_PARENT_BASE_URL=${NETDATA_PARENT_BASE_URL}"
} | tee "${RUN_DIR}/experiment_config.txt"

kubectl -n "${NAMESPACE}" get pods -l app="${APP}",exp="${EXP}" -o wide | tee "${RUN_DIR}/pods_before.txt"
kubectl -n "${NAMESPACE}" get deploy | grep "${APP}" | tee "${RUN_DIR}/deploy_before.txt"
kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp | tail -n 50 | tee "${RUN_DIR}/events_before.txt"

curl -s "http://${POD_IP}:18080/healthz" | tee "${RUN_DIR}/focus_health_before.json"
echo ""
curl -s "http://${MEAS_SVC_IP}:18080/healthz" | tee "${RUN_DIR}/service_health_before.json"
echo ""

log_info "Starting nvidia-smi GPU monitor..."
ssh "${NODE_SSH}" \
  "nvidia-smi --query-gpu=timestamp,index,name,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm,clocks.mem --format=csv -l 1" \
  > "${RUN_DIR}/nvidia_smi_gpu_1s.csv" 2> "${RUN_DIR}/nvidia_smi_gpu_1s.err" &
GPU_PID=$!

log_info "Starting kubectl top monitor..."
(
  while true; do
    echo "timestamp,$(date -Is)"
    echo "[node]"
    kubectl top node "${GPU_NODE_NAME}" --no-headers || true
    echo "[pods]"
    kubectl -n "${NAMESPACE}" top pod -l app="${APP}",exp="${EXP}" --no-headers || true
    echo "----"
    sleep 1
  done
) > "${RUN_DIR}/kubectl_top_1s.log" 2>&1 &
TOP_PID=$!

sleep 3

START_EPOCH=$(date +%s)
START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "START_EPOCH=${START_EPOCH}" | tee "${RUN_DIR}/time_window.txt"
echo "START_ISO=${START_ISO}" | tee -a "${RUN_DIR}/time_window.txt"

log_info "Start vm_aggregator collector..."
python3 "${VM_AGG_COLLECTOR}" \
  --aggregator "${VM_AGGREGATOR}" \
  --out "${RUN_DIR}/vm_aggregator_timeseries.csv" \
  --seconds "${DURATION}" \
  --interval "${VM_AGG_INTERVAL}" \
  --node "${GPU_NODE_NAME}" \
  --namespace "${NAMESPACE}" \
  --vm-url "${VM_URL}" \
  --netdata-url "${NETDATA_URL}" \
  --netdata-child-url "${NETDATA_CHILD_URL}" \
  --netdata-parent-base-url "${NETDATA_PARENT_BASE_URL}" \
  --mode fast \
  > "${RUN_DIR}/vm_aggregator_timeseries.log" 2>&1 &
VM_AGG_PID=$!

log_info "Start measurement client with concurrency=${MEAS_CONCURRENCY}, duration=${DURATION}s"
python3 "${CLIENT}" \
  --role measurement \
  --url "${INFER_URL}" \
  --image "${IMG}" \
  --duration "${DURATION}" \
  --concurrency "${MEAS_CONCURRENCY}" \
  --interval "${MEAS_INTERVAL}" \
  --timeout "${TIMEOUT_SEC}" \
  --output "${RUN_DIR}/measurement_raw.csv" \
  > "${RUN_DIR}/measurement.log" 2>&1

END_EPOCH=$(date +%s)
END_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "END_EPOCH=${END_EPOCH}" | tee -a "${RUN_DIR}/time_window.txt"
echo "END_ISO=${END_ISO}" | tee -a "${RUN_DIR}/time_window.txt"

log_info "Stopping monitors..."
kill "${GPU_PID}" "${TOP_PID}" 2>/dev/null || true
kill "${VM_AGG_PID}" 2>/dev/null || true
wait "${VM_AGG_PID}" || true
sleep 2

kubectl -n "${NAMESPACE}" get pods -l app="${APP}",exp="${EXP}" -o wide | tee "${RUN_DIR}/pods_after.txt"
kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp | tail -n 50 | tee "${RUN_DIR}/events_after.txt"

log_info "Extract vm_aggregator training-ready features..."
python3 "${VM_AGG_TRAINING}" \
  --input "${RUN_DIR}/vm_aggregator_timeseries.csv" \
  > "${RUN_DIR}/vm_aggregator_training_features.log" 2>&1 || true

log_info "Exporting VictoriaMetrics query_range snapshots..."
python3 - "${VM_URL}" "${START_EPOCH}" "${END_EPOCH}" "${RUN_DIR}" "${NAMESPACE}" "${EXP}" <<'PY'
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

vm_url = sys.argv[1].rstrip("/")
start = sys.argv[2]
end = sys.argv[3]
run_dir = Path(sys.argv[4])
namespace = sys.argv[5]
exp = sys.argv[6]

queries = {
    "dcgm_gpu_util": "DCGM_FI_DEV_GPU_UTIL",
    "dcgm_mem_copy_util": "DCGM_FI_DEV_MEM_COPY_UTIL",
    "dcgm_fb_used": "DCGM_FI_DEV_FB_USED",
    "dcgm_fb_free": "DCGM_FI_DEV_FB_FREE",
    "dcgm_power_usage": "DCGM_FI_DEV_POWER_USAGE",
    "dcgm_gpu_temp": "DCGM_FI_DEV_GPU_TEMP",
    "dcgm_sm_clock": "DCGM_FI_DEV_SM_CLOCK",
    "dcgm_mem_clock": "DCGM_FI_DEV_MEM_CLOCK",
    "node_cpu_util_percent": "100 - avg by (instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[1m])) * 100",
    "node_mem_util_percent": "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100",
    "pod_cpu_usage": f"sum by (pod) (rate(container_cpu_usage_seconds_total{{namespace=\"{namespace}\",pod=~\".*{exp}.*\",container!=\"\"}}[1m]))",
    "pod_mem_working_set": f"container_memory_working_set_bytes{{namespace=\"{namespace}\",pod=~\".*{exp}.*\",container!=\"\"}}",
}

out_dir = run_dir / "vm_metrics"
out_dir.mkdir(exist_ok=True)
for name, query in queries.items():
    params = {"query": query, "start": start, "end": end, "step": "1s"}
    url = vm_url + "/api/v1/query_range?" + urllib.parse.urlencode(params)
    out_path = out_dir / f"{name}.json"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            out_path.write_bytes(resp.read())
    except Exception as exc:
        (out_dir / f"{name}.error.txt").write_text(str(exc), encoding="utf-8")
PY

python3 "${TIMELINE_PLOTTER}" "${RUN_DIR}" > "${RUN_DIR}/plot_full_timeline.log" 2>&1 || true
python3 "${RESOURCE_PLOTTER}" "${RUN_DIR}" > "${RUN_DIR}/plot_resource_overview.log" 2>&1 || true

python3 - "${RUN_DIR}" <<'PY' | tee "${RUN_DIR}/summary.txt"
import csv
import math
import statistics
import sys
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
clean = [row for row in rows if str(row.get("success", "")).strip().lower() in {"1", "1.0", "true"}]
print("rows:", len(rows))
print("success rows:", len(clean))
for col in ["e2e_latency_ms", "server_latency_ms", "server_total_latency_ms"]:
    values = [to_float(row.get(col)) for row in clean]
    values = [v for v in values if v is not None]
    if values:
        print(f"{col}_mean:", round(statistics.fmean(values), 3))
        print(f"{col}_p95:", round(percentile(values, 0.95), 3))
print("result_dir:", run_dir)
PY

log_info "Done."
log_info "RUN_DIR=${RUN_DIR}"
