#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="intent-lab"
APP="yolo26n"
EXP="task3-saturation"
NODE_NAME="icclz1"
NODE_SSH="icclz1@100.105.48.97"
VM_URL="${VM_URL:-http://100.68.32.118:31888}"
NETDATA_URL="${NETDATA_URL:-http://100.68.32.118:32163}"
NETDATA_CHILD_URL="${NETDATA_CHILD_URL:-$NETDATA_URL}"
NETDATA_PARENT_BASE_URL="${NETDATA_PARENT_BASE_URL:-$NETDATA_URL}"

DURATION=${DURATION:-300}
MEAS_CONCURRENCY=${MEAS_CONCURRENCY:-12}
MEAS_INTERVAL=${MEAS_INTERVAL:-1.0}
TIMEOUT_SEC=${TIMEOUT_SEC:-20}
REPEAT=${REPEAT:-1}
MEAS_SVC_NAME=${MEAS_SVC_NAME:-yolo26n-task3}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPERIMENT_LAYER_DIR="$(cd "${BASE_DIR}/.." && pwd)"
SPLIT_ROOT="$(cd "${EXPERIMENT_LAYER_DIR}/.." && pwd)"
MONITORING_DIR="${SPLIT_ROOT}/01-monitoring-layer"
CLIENT="${BASE_DIR}/common/request_client_parallel.py"
STABLE_FINDER="${BASE_DIR}/common/task3_find_stable_window.py"
STABLE_ANALYZER="${BASE_DIR}/common/analyze_task3_stable_latency.py"
TIMELINE_PLOTTER="${BASE_DIR}/common/plot_task3_full_timeline.py"
RESOURCE_PLOTTER="${BASE_DIR}/common/plot_resource_overview.py"
VM_AGG_COLLECTOR="${BASE_DIR}/../thermal_analysis/collect_vm_aggregator_csv.py"
VM_AGG_TRAINING="${BASE_DIR}/common/extract_vmagg_training_features.py"
VM_AGGREGATOR="${MONITORING_DIR}/vm_aggregator.py"
IMG="${EXPERIMENT_LAYER_DIR}/yolo26_k8s/test_images/sanity_input.png"
VM_AGG_INTERVAL="${VM_AGG_INTERVAL:-1.0}"

RESULT_ROOT="${BASE_DIR}/results/saturation_multi_pod"
RUN_ID="task3_service_c${MEAS_CONCURRENCY}_repeat${REPEAT}_${DURATION}s_$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${RESULT_ROOT}/${RUN_ID}"
mkdir -p "${RESULT_ROOT}" "${RUN_DIR}"

echo "[INFO] RUN_DIR=${RUN_DIR}"

cd "${BASE_DIR}"

if [ -f ~/AutoScale/iccl/bin/activate ]; then
  source ~/AutoScale/iccl/bin/activate
fi

echo "[INFO] Checking pods..."
kubectl -n "${NAMESPACE}" get pods -o wide -l app="${APP}",exp="${EXP}" | tee "${RUN_DIR}/pods_before.txt"
kubectl -n "${NAMESPACE}" get deploy | grep yolo26 | tee "${RUN_DIR}/deploy_before.txt"
kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp | tail -n 50 | tee "${RUN_DIR}/events_before.txt"

RUNNING_COUNT=$(kubectl -n "${NAMESPACE}" get pods \
  -l app="${APP}",exp="${EXP}" \
  -o jsonpath='{range .items[*]}{.status.phase}{"\n"}{end}' | grep -c '^Running$' || true)

EXPECTED_PODS="${EXPECTED_PODS:-4}"
if [ "${RUNNING_COUNT}" -ne "${EXPECTED_PODS}" ]; then
  echo "[ERROR] Expected ${EXPECTED_PODS} Running pods, but got ${RUNNING_COUNT}."
  echo "[ERROR] Stop experiment. Please fix Pending/CrashLoop pods first."
  exit 1
fi

FOCUS_IP=$(kubectl -n "${NAMESPACE}" get pod \
  -l app="${APP}",exp="${EXP}",role=focus \
  -o jsonpath='{.items[0].status.podIP}')

FOCUS_POD=$(kubectl -n "${NAMESPACE}" get pod \
  -l app="${APP}",exp="${EXP}",role=focus \
  -o jsonpath='{.items[0].metadata.name}')

MEAS_SVC_IP=$(kubectl -n "${NAMESPACE}" get svc "${MEAS_SVC_NAME}" \
  -o jsonpath='{.spec.clusterIP}')

FOCUS_INFER_URL="http://${FOCUS_IP}:18080/infer?repeat=${REPEAT}"
MEASUREMENT_INFER_URL="http://${MEAS_SVC_IP}:18080/infer?repeat=${REPEAT}"

{
  echo "RUN_ID=${RUN_ID}"
  echo "RUN_DIR=${RUN_DIR}"
  echo "NAMESPACE=${NAMESPACE}"
  echo "APP=${APP}"
  echo "EXP=${EXP}"
  echo "NODE_NAME=${NODE_NAME}"
  echo "FOCUS_POD=${FOCUS_POD}"
  echo "FOCUS_IP=${FOCUS_IP}"
  echo "MEAS_SVC_NAME=${MEAS_SVC_NAME}"
  echo "MEAS_SVC_IP=${MEAS_SVC_IP}"
  echo "FOCUS_INFER_URL=${FOCUS_INFER_URL}"
  echo "MEASUREMENT_INFER_URL=${MEASUREMENT_INFER_URL}"
  echo "DURATION=${DURATION}"
  echo "MEAS_CONCURRENCY=${MEAS_CONCURRENCY}"
  echo "REPEAT=${REPEAT}"
  echo "MEAS_INTERVAL=${MEAS_INTERVAL}"
  echo "TIMEOUT_SEC=${TIMEOUT_SEC}"
  echo "VM_URL=${VM_URL}"
  echo "NETDATA_URL=${NETDATA_URL}"
  echo "NETDATA_CHILD_URL=${NETDATA_CHILD_URL}"
  echo "NETDATA_PARENT_BASE_URL=${NETDATA_PARENT_BASE_URL}"
} | tee "${RUN_DIR}/experiment_config.txt"

echo "[INFO] Testing focus health..."
curl -s "http://${FOCUS_IP}:18080/healthz" | tee "${RUN_DIR}/focus_health_before.json"
echo ""

echo "[INFO] Testing service health..."
curl -s "http://${MEAS_SVC_IP}:18080/healthz" | tee "${RUN_DIR}/service_health_before.json"
echo ""

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
    kubectl -n "${NAMESPACE}" top pod -l app="${APP}",exp="${EXP}" --no-headers || true
    echo "----"
    sleep 1
  done
) > "${RUN_DIR}/kubectl_top_1s.log" 2>&1 &
TOP_PID=$!

echo "[INFO] Monitor PIDs: GPU_PID=${GPU_PID}, TOP_PID=${TOP_PID}" | tee "${RUN_DIR}/monitor_pids.txt"

sleep 3

START_EPOCH=$(date +%s)
START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

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

if [ "${MEAS_CONCURRENCY}" -gt 1 ]; then
  echo "[INFO] Starting measurement client: service=${MEAS_SVC_NAME}, concurrency=${MEAS_CONCURRENCY}, duration=${DURATION}s"
else
  echo "[INFO] Starting measurement client: service=${MEAS_SVC_NAME}, interval=${MEAS_INTERVAL}s, duration=${DURATION}s"
fi
python3 "${CLIENT}" \
  --role measurement \
  --url "${MEASUREMENT_INFER_URL}" \
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

echo "[INFO] Stopping monitors..."
kill "${GPU_PID}" "${TOP_PID}" 2>/dev/null || true
kill "${VM_AGG_PID}" 2>/dev/null || true
wait "${VM_AGG_PID}" || true
sleep 2

kubectl -n "${NAMESPACE}" get pods -o wide -l app="${APP}",exp="${EXP}" | tee "${RUN_DIR}/pods_after.txt"
kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp | tail -n 50 | tee "${RUN_DIR}/events_after.txt"

echo "[INFO] Extract vm_aggregator training-ready features..."
python3 "${VM_AGG_TRAINING}" \
  --input "${RUN_DIR}/vm_aggregator_timeseries.csv" \
  > "${RUN_DIR}/vm_aggregator_training_features.log" 2>&1 || true

echo "[INFO] Querying VM / VictoriaMetrics if VM_URL is set..."

if [ -n "${VM_URL:-}" ]; then
python3 - "${VM_URL}" "${START_EPOCH}" "${END_EPOCH}" "${RUN_DIR}" <<'PY'
import sys
import json
import urllib.parse
import urllib.request
from pathlib import Path

vm_url = sys.argv[1].rstrip("/")
start = sys.argv[2]
end = sys.argv[3]
run_dir = Path(sys.argv[4])

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
    "pod_cpu_usage": "sum by (pod) (rate(container_cpu_usage_seconds_total{namespace=\"intent-lab\",pod=~\"yolo26n-task3.*\",container!=\"\"}[1m]))",
    "pod_mem_working_set": "container_memory_working_set_bytes{namespace=\"intent-lab\",pod=~\"yolo26n-task3.*\",container!=\"\"}",
}

out_dir = run_dir / "vm_metrics"
out_dir.mkdir(exist_ok=True)

for name, query in queries.items():
    params = {
        "query": query,
        "start": start,
        "end": end,
        "step": "1s",
    }
    url = vm_url + "/api/v1/query_range?" + urllib.parse.urlencode(params)
    out_path = out_dir / f"{name}.json"

    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
        out_path.write_bytes(data)
        print(f"[VM] saved {name} -> {out_path}")
    except Exception as e:
        err_path = out_dir / f"{name}.error.txt"
        err_path.write_text(str(e))
        print(f"[VM][ERROR] {name}: {e}")
PY
else
  echo "[INFO] VM_URL is not set. Skip VictoriaMetrics query_range export." | tee "${RUN_DIR}/vm_metrics_skipped.txt"
  echo "[INFO] You can later query VM with this window:" | tee -a "${RUN_DIR}/vm_metrics_skipped.txt"
  cat "${RUN_DIR}/time_window.txt" | tee -a "${RUN_DIR}/vm_metrics_skipped.txt"
fi

echo "[INFO] Quick summary..."

python3 - "${RUN_DIR}" <<'PY' | tee "${RUN_DIR}/summary.txt"
import sys
from pathlib import Path
import pandas as pd

run_dir = Path(sys.argv[1])

for name in ["measurement_raw.csv"]:
    path = run_dir / name
    print("\n==", name, "==")
    if not path.exists():
        print("missing:", path)
        continue

    df = pd.read_csv(path)
    clean = df[df["success"] == 1].copy()

    print("rows:", len(df))
    print("success rate:", df["success"].mean() if len(df) else None)

    print("\nerror types:")
    print(df["error_type"].value_counts(dropna=False))

    if len(clean):
        print("\nclean e2e latency ms:")
        print(clean["e2e_latency_ms"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

        print("\nclean server latency ms:")
        print(clean["server_latency_ms"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

        if "server_total_latency_ms" in clean.columns:
            print("\nclean server total latency ms:")
            print(clean["server_total_latency_ms"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

    print("\npods:")
    print(df["server_pod_name"].value_counts(dropna=False))

vm_path = run_dir / "vm_aggregator_timeseries.csv"
if vm_path.exists():
    print(f"\nvm_aggregator_timeseries_csv: {vm_path}")
train_path = run_dir / "vm_aggregator_training_features.csv"
if train_path.exists():
    print(f"vm_aggregator_training_features_csv: {train_path}")

print("\n[INFO] Result directory:")
print(run_dir)
PY

echo "[INFO] Post-processing..."

if python3 "${STABLE_FINDER}" "${RUN_DIR}" | tee "${RUN_DIR}/stable_window_detection.txt"; then
  python3 - "${RUN_DIR}" <<'PY'
import sys
from pathlib import Path
import pandas as pd

run_dir = Path(sys.argv[1])
auto_path = run_dir / "gpu_stable_window_auto.csv"
out_path = run_dir / "stable_windows.csv"

df = pd.read_csv(auto_path)

if "t_rel_sec" not in df.columns:
    raise SystemExit("gpu_stable_window_auto.csv missing t_rel_sec column")

rows = [{
    "window_id": "stable_1",
    "start_s": round(float(df["t_rel_sec"].iloc[0]), 3),
    "end_s": round(float(df["t_rel_sec"].iloc[-1]), 3),
    "duration_s": round(float(df["t_rel_sec"].iloc[-1] - df["t_rel_sec"].iloc[0]), 3),
    "gpu_mean": round(pd.to_numeric(df["gpu_util"], errors="coerce").mean(), 3),
    "gpu_median": round(pd.to_numeric(df["gpu_util"], errors="coerce").median(), 3),
    "power_mean": round(pd.to_numeric(df["power_w"], errors="coerce").mean(), 3),
    "power_median": round(pd.to_numeric(df["power_w"], errors="coerce").median(), 3),
    "temp_mean": round(pd.to_numeric(df["temp_c"], errors="coerce").mean(), 3),
}]

pd.DataFrame(rows).to_csv(out_path, index=False)
print(f"[INFO] Saved {out_path}")
PY

  python3 "${STABLE_ANALYZER}" "${RUN_DIR}" | tee "${RUN_DIR}/stable_latency_summary.txt"
else
  echo "[WARN] Stable window detection failed; skip stable latency analysis." | tee "${RUN_DIR}/stable_latency_summary.txt"
fi

python3 "${TIMELINE_PLOTTER}" "${RUN_DIR}" | tee "${RUN_DIR}/plot_full_timeline.log"
python3 "${RESOURCE_PLOTTER}" "${RUN_DIR}" | tee "${RUN_DIR}/plot_resource_overview.log"

echo "[INFO] Done."
echo "[INFO] RUN_DIR=${RUN_DIR}"
