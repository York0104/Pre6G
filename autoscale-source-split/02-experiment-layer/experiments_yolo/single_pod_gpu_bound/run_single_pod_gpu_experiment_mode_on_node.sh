#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-intent-lab}"
APP="${APP:-yolo26n}"
EXP="${EXP:-single-gpu-experiment}"
GPU_NODE_NAME="${GPU_NODE_NAME:?missing GPU_NODE_NAME, e.g. iccl-s3-251230}"
NODE_SSH="${NODE_SSH:?missing NODE_SSH, e.g. mirc516@100.90.127.1}"

IMAGE_REF="${IMAGE_REF:-local/yolo26n:0.2}"
IMAGE_PULL_POLICY="${IMAGE_PULL_POLICY:-Never}"
IMAGE_PULL_SECRET="${IMAGE_PULL_SECRET:-}"

YOLO_MODEL="${YOLO_MODEL:-yolo26m.pt}"
YOLO_IMGSZ="${YOLO_IMGSZ:-1280}"
BATCH_SIZE="${BATCH_SIZE:-8}"
REPEAT="${REPEAT:-2}"
DURATION="${DURATION:-300}"
START_DELAY_SECONDS="${START_DELAY_SECONDS:-15}"
WARMUP_ITERS="${WARMUP_ITERS:-2}"
PROGRESS_INTERVAL_SECONDS="${PROGRESS_INTERVAL_SECONDS:-5}"

CPU_REQUEST="${CPU_REQUEST:-2000m}"
CPU_LIMIT="${CPU_LIMIT:-8000m}"
MEMORY_REQUEST="${MEMORY_REQUEST:-6Gi}"
MEMORY_LIMIT="${MEMORY_LIMIT:-16Gi}"
MONITOR_HEADROOM_SECONDS="${MONITOR_HEADROOM_SECONDS:-30}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-180s}"
POD_WAIT_TIMEOUT_SECONDS="${POD_WAIT_TIMEOUT_SECONDS:-480}"

VM_URL="${VM_URL:-http://140.113.179.9:31888}"
NETDATA_URL="${NETDATA_URL:-http://140.113.179.9:32163}"
NETDATA_CHILD_URL="${NETDATA_CHILD_URL:-$NETDATA_URL}"
NETDATA_PARENT_BASE_URL="${NETDATA_PARENT_BASE_URL:-$NETDATA_URL}"
VM_AGG_INTERVAL="${VM_AGG_INTERVAL:-1.0}"
CLEANUP_ON_EXIT="${CLEANUP_ON_EXIT:-1}"
MASTER_PYTHON_BIN="${MASTER_PYTHON_BIN:-/home/icclz2/Pre6G/iccl/bin/python}"
MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/pre6g-matplotlib}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPERIMENT_LAYER_DIR="$(cd "${BASE_DIR}/.." && pwd)"
SPLIT_ROOT="$(cd "${EXPERIMENT_LAYER_DIR}/.." && pwd)"
MONITORING_DIR="${SPLIT_ROOT}/01-monitoring-layer"
RESOURCE_PLOTTER="${BASE_DIR}/common/plot_resource_overview.py"
VM_AGG_COLLECTOR="${BASE_DIR}/../thermal_analysis/collect_vm_aggregator_csv.py"
VM_AGG_TRAINING="${BASE_DIR}/common/extract_vmagg_training_features.py"
VM_AGGREGATOR="${MONITORING_DIR}/vm_aggregator.py"
GPU_BURN_SCRIPT_SRC="${EXPERIMENT_LAYER_DIR}/yolo26_workload/gpu_burn.py"

RESULT_ROOT="${RESULT_ROOT:-${BASE_DIR}/results/single_pod_gpu_experiment_mode}"
MODEL_SLUG="$(printf '%s' "${YOLO_MODEL}" | tr '/:.' '_' | tr -cd '[:alnum:]_-')"
RUN_ID="single_gpu_exp_${GPU_NODE_NAME}_${MODEL_SLUG}_img${YOLO_IMGSZ}_b${BATCH_SIZE}_r${REPEAT}_${DURATION}s_$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${RESULT_ROOT}/${RUN_ID}"
MANIFEST_RENDERED="/tmp/${RUN_ID}.yaml"
mkdir -p "${RESULT_ROOT}" "${RUN_DIR}"

SHORT_MODEL_SLUG="${MODEL_SLUG:0:12}"
RUN_STAMP="$(date +%H%M%S)"
POD_NAME="gpu-burn-${SHORT_MODEL_SLUG}-i${YOLO_IMGSZ}-b${BATCH_SIZE}-${RUN_STAMP}"
POD_NAME="${POD_NAME//_/-}"
CONFIGMAP_NAME="gpu-burn-script-${RUN_STAMP}"
MONITOR_SECONDS=$(( DURATION + START_DELAY_SECONDS + MONITOR_HEADROOM_SECONDS ))

log_info() {
  echo "[INFO] $*"
}

log_error() {
  echo "[ERROR] $*" >&2
}

cleanup() {
  kill "${GPU_PID:-}" "${TOP_PID:-}" "${VM_AGG_PID:-}" >/dev/null 2>&1 || true
  if [ "${CLEANUP_ON_EXIT}" = "1" ]; then
    kubectl delete pod "${POD_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
    kubectl delete configmap "${CONFIGMAP_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [ ! -f "${GPU_BURN_SCRIPT_SRC}" ]; then
  log_error "Missing gpu burn script: ${GPU_BURN_SCRIPT_SRC}"
  exit 2
fi

log_info "RUN_DIR=${RUN_DIR}"
log_info "Checking target node ${GPU_NODE_NAME}..."
kubectl get node "${GPU_NODE_NAME}" -o wide

log_info "Creating script ConfigMap..."
kubectl -n "${NAMESPACE}" delete configmap "${CONFIGMAP_NAME}" --ignore-not-found >/dev/null 2>&1 || true
kubectl -n "${NAMESPACE}" create configmap "${CONFIGMAP_NAME}" --from-file=gpu_burn.py="${GPU_BURN_SCRIPT_SRC}"

cat > "${MANIFEST_RENDERED}" <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${POD_NAME}
  namespace: ${NAMESPACE}
  labels:
    app: ${APP}
    exp: ${EXP}
    role: focus
spec:
  restartPolicy: Never
  runtimeClassName: nvidia
EOF

if [ -n "${IMAGE_PULL_SECRET}" ]; then
  cat >> "${MANIFEST_RENDERED}" <<EOF
  imagePullSecrets:
    - name: ${IMAGE_PULL_SECRET}
EOF
fi

cat >> "${MANIFEST_RENDERED}" <<EOF
  nodeSelector:
    kubernetes.io/hostname: ${GPU_NODE_NAME}
  containers:
    - name: yolo26-burn
      image: ${IMAGE_REF}
      imagePullPolicy: ${IMAGE_PULL_POLICY}
      command: ["python3", "/opt/pre6g/gpu_burn.py"]
      env:
        - name: YOLO26_MODEL
          value: "${YOLO_MODEL}"
        - name: YOLO26_DEVICE
          value: "cuda:0"
        - name: YOLO26_IMGSZ
          value: "${YOLO_IMGSZ}"
        - name: YOLO26_BATCH_SIZE
          value: "${BATCH_SIZE}"
        - name: YOLO26_REPEAT
          value: "${REPEAT}"
        - name: YOLO26_BURN_DURATION_SECONDS
          value: "${DURATION}"
        - name: YOLO26_BURN_START_DELAY_SECONDS
          value: "${START_DELAY_SECONDS}"
        - name: YOLO26_WARMUP_ITERS
          value: "${WARMUP_ITERS}"
        - name: YOLO26_PROGRESS_INTERVAL_SECONDS
          value: "${PROGRESS_INTERVAL_SECONDS}"
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
      volumeMounts:
        - name: gpu-burn-script
          mountPath: /opt/pre6g
  volumes:
    - name: gpu-burn-script
      configMap:
        name: ${CONFIGMAP_NAME}
        defaultMode: 0555
EOF

log_info "Applying experiment pod..."
kubectl apply -f "${MANIFEST_RENDERED}"

{
  echo "RUN_ID=${RUN_ID}"
  echo "RUN_DIR=${RUN_DIR}"
  echo "POD_NAME=${POD_NAME}"
  echo "NAMESPACE=${NAMESPACE}"
  echo "GPU_NODE_NAME=${GPU_NODE_NAME}"
  echo "NODE_SSH=${NODE_SSH}"
  echo "IMAGE_REF=${IMAGE_REF}"
  echo "YOLO_MODEL=${YOLO_MODEL}"
  echo "YOLO_IMGSZ=${YOLO_IMGSZ}"
  echo "BATCH_SIZE=${BATCH_SIZE}"
  echo "REPEAT=${REPEAT}"
  echo "TASK=gpu_bound_experiment"
  echo "DURATION=${DURATION}"
  echo "START_DELAY_SECONDS=${START_DELAY_SECONDS}"
  echo "WARMUP_ITERS=${WARMUP_ITERS}"
  echo "PROGRESS_INTERVAL_SECONDS=${PROGRESS_INTERVAL_SECONDS}"
  echo "CPU_REQUEST=${CPU_REQUEST}"
  echo "CPU_LIMIT=${CPU_LIMIT}"
  echo "MEMORY_REQUEST=${MEMORY_REQUEST}"
  echo "MEMORY_LIMIT=${MEMORY_LIMIT}"
  echo "MONITOR_SECONDS=${MONITOR_SECONDS}"
} | tee "${RUN_DIR}/experiment_config.txt"

kubectl -n "${NAMESPACE}" get pods -o wide | tee "${RUN_DIR}/pods_before.txt"
kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp | tail -n 80 | tee "${RUN_DIR}/events_before.txt"
kubectl -n "${NAMESPACE}" describe pod "${POD_NAME}" | tee "${RUN_DIR}/describe_before.txt"

log_info "Waiting for pod to enter Running..."
SECONDS_WAITED=0
while true; do
  PHASE="$(kubectl -n "${NAMESPACE}" get pod "${POD_NAME}" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  if [ "${PHASE}" = "Running" ]; then
    break
  fi
  if [ "${PHASE}" = "Failed" ] || [ "${PHASE}" = "Succeeded" ]; then
    log_error "Pod reached terminal phase early: ${PHASE}"
    break
  fi
  if [ "${SECONDS_WAITED}" -ge "${POD_WAIT_TIMEOUT_SECONDS}" ]; then
    log_error "Timed out waiting for pod to run."
    exit 3
  fi
  sleep 1
  SECONDS_WAITED=$((SECONDS_WAITED + 1))
done

START_EPOCH=$(date +%s)
START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "START_EPOCH=${START_EPOCH}" | tee "${RUN_DIR}/time_window.txt"
echo "START_ISO=${START_ISO}" | tee -a "${RUN_DIR}/time_window.txt"
cat > "${RUN_DIR}/phase_windows.csv" <<EOF
phase,start_s,end_s
warm-up,0,${START_DELAY_SECONDS}
steady-state,${START_DELAY_SECONDS},$((START_DELAY_SECONDS + DURATION))
cooldown,$((START_DELAY_SECONDS + DURATION)),$((START_DELAY_SECONDS + DURATION + MONITOR_HEADROOM_SECONDS))
EOF

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
    kubectl -n "${NAMESPACE}" top pod "${POD_NAME}" --no-headers || true
    echo "----"
    sleep 1
  done
) > "${RUN_DIR}/kubectl_top_1s.log" 2>&1 &
TOP_PID=$!

log_info "Start vm_aggregator collector..."
python3 "${VM_AGG_COLLECTOR}" \
  --aggregator "${VM_AGGREGATOR}" \
  --out "${RUN_DIR}/vm_aggregator_timeseries.csv" \
  --seconds "${MONITOR_SECONDS}" \
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

log_info "Waiting for experiment pod to complete..."
SECONDS_WAITED=0
while true; do
  PHASE="$(kubectl -n "${NAMESPACE}" get pod "${POD_NAME}" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  if [ "${PHASE}" = "Succeeded" ] || [ "${PHASE}" = "Failed" ]; then
    break
  fi
  if [ "${SECONDS_WAITED}" -ge "${POD_WAIT_TIMEOUT_SECONDS}" ]; then
    log_error "Timed out waiting for experiment completion."
    break
  fi
  sleep 2
  SECONDS_WAITED=$((SECONDS_WAITED + 2))
done

if [ "${MONITOR_HEADROOM_SECONDS}" -gt 0 ]; then
  log_info "Cooldown observation for ${MONITOR_HEADROOM_SECONDS}s..."
  sleep "${MONITOR_HEADROOM_SECONDS}"
fi

END_EPOCH=$(date +%s)
END_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "END_EPOCH=${END_EPOCH}" | tee -a "${RUN_DIR}/time_window.txt"
echo "END_ISO=${END_ISO}" | tee -a "${RUN_DIR}/time_window.txt"

log_info "Stopping monitors..."
kill "${GPU_PID}" "${TOP_PID}" 2>/dev/null || true
kill "${VM_AGG_PID}" 2>/dev/null || true
wait "${VM_AGG_PID}" || true
sleep 2

kubectl -n "${NAMESPACE}" get pods -o wide | tee "${RUN_DIR}/pods_after.txt" || true
kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp | tail -n 80 | tee "${RUN_DIR}/events_after.txt" || true
kubectl -n "${NAMESPACE}" describe pod "${POD_NAME}" | tee "${RUN_DIR}/describe_after.txt" || true
kubectl -n "${NAMESPACE}" logs "${POD_NAME}" > "${RUN_DIR}/gpu_burn.log" 2>&1 || true

cp -f "${RUN_DIR}/nvidia_smi_gpu_1s.csv" "${RUN_DIR}/worker_nvidia_smi_1s.csv" 2>/dev/null || true
cp -f "${RUN_DIR}/kubectl_top_1s.log" "${RUN_DIR}/kubectl_top_node_1s.log" 2>/dev/null || true

log_info "Extracting pod summary from logs..."
python3 - "${RUN_DIR}/gpu_burn.log" "${RUN_DIR}/gpu_burn_summary.json" <<'PY'
import json
import sys
from pathlib import Path

log_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
summary = None
progress = []

if log_path.exists():
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("GPU_BURN_PROGRESS_JSON:"):
            payload = line.split(":", 1)[1].strip()
            try:
                progress.append(json.loads(payload))
            except Exception:
                pass
        if line.startswith("GPU_BURN_SUMMARY_JSON:"):
            payload = line.split(":", 1)[1].strip()
            try:
                summary = json.loads(payload)
            except Exception:
                summary = None

if summary is None:
    summary = {"success": False, "error": "summary_missing"}

summary["progress_samples"] = len(progress)
out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY

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

MPLCONFIGDIR="${MPLCONFIGDIR}" "${MASTER_PYTHON_BIN}" "${RESOURCE_PLOTTER}" "${RUN_DIR}" > "${RUN_DIR}/plot_resource_overview.log" 2>&1 || true
MPLCONFIGDIR="${MPLCONFIGDIR}" "${MASTER_PYTHON_BIN}" "${EXPERIMENT_LAYER_DIR}/experiments_benchmark/plot_remote_benchmark_run.py" --run-dir "${RUN_DIR}" > "${RUN_DIR}/plot_benchmark_compat.log" 2>&1 || true

mkdir -p "${RUN_DIR}/plots"
if [ -f "${RUN_DIR}/resource_utilization.png" ]; then
  cp -f "${RUN_DIR}/resource_utilization.png" "${RUN_DIR}/plots/resource_utilization.png"
fi

python3 - "${RUN_DIR}" <<'PY' | tee "${RUN_DIR}/summary.txt"
import csv
import json
import math
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
summary_path = run_dir / "gpu_burn_summary.json"
summary = {}
if summary_path.exists():
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

gpu_stats = {
    "gpu_util_avg": None,
    "gpu_util_p95": None,
    "gpu_util_peak": None,
    "vram_used_mib_peak": None,
    "power_draw_w_peak": None,
}

csv_path = run_dir / "nvidia_smi_gpu_1s.csv"
if csv_path.exists():
    vals = []
    mem = []
    power = []
    with csv_path.open() as fh:
      reader = csv.DictReader(fh, skipinitialspace=True)
      for row in reader:
        def parse_num(raw):
          text = (raw or "").strip()
          if not text:
            return None
          try:
            return float(text.split()[0])
          except Exception:
            return None
        v = parse_num(row.get("utilization.gpu [%]"))
        m = parse_num(row.get("memory.used [MiB]"))
        p = parse_num(row.get("power.draw [W]"))
        if v is not None:
          vals.append(v)
        if m is not None:
          mem.append(m)
        if p is not None:
          power.append(p)
    if vals:
      vals_sorted = sorted(vals)
      idx = max(0, int(len(vals_sorted) * 0.95) - 1)
      gpu_stats["gpu_util_avg"] = round(sum(vals) / len(vals), 3)
      gpu_stats["gpu_util_p95"] = round(vals_sorted[idx], 3)
      gpu_stats["gpu_util_peak"] = round(max(vals), 3)
    if mem:
      gpu_stats["vram_used_mib_peak"] = round(max(mem), 3)
    if power:
      gpu_stats["power_draw_w_peak"] = round(max(power), 3)

print("burn_success:", summary.get("success"))
print("iter_count:", summary.get("iter_count"))
print("images_per_second:", summary.get("images_per_second"))
for key, value in gpu_stats.items():
    print(f"{key}:", value)
print("result_dir:", run_dir)
PY

python3 - "${RUN_DIR}" <<'PY' > "${RUN_DIR}/benchmark_compat_summary.json"
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
summary = {
    "success": True,
    "run_dir": str(run_dir),
    "artifacts": {
        "combined_monitor_csv": str(run_dir / "combined_monitor.csv"),
        "resource_plot": str(run_dir / "resource_utilization.png"),
        "gpu_resource_plot": str(run_dir / "plots" / "gpu_resource_overview.png"),
        "phase_windows_csv": str(run_dir / "phase_windows.csv"),
        "gpu_burn_summary_json": str(run_dir / "gpu_burn_summary.json"),
    },
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY

log_info "Done."
log_info "RUN_DIR=${RUN_DIR}"
