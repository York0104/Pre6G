#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:-B_thermal_yolo26_3inst_smoke_$(date +%Y%m%d_%H%M%S)}"
export RUN_ID

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_LAYER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPLIT_ROOT="$(cd "${EXPERIMENT_LAYER_DIR}/.." && pwd)"
MONITORING_DIR="${SPLIT_ROOT}/01-monitoring-layer"

NS="${NS:-intent-lab}"
WORKER_NODE="${WORKER_NODE:-icclz1}"
WORKER_IP="${WORKER_IP:-140.113.179.6}"
WORKER_USER="${WORKER_USER:-${WORKER_NODE}}"
WORKER_SSH_ALIAS="${WORKER_SSH_ALIAS:-icclz1-gpu}"
WORKER_SSH="${WORKER_SSH:-$WORKER_SSH_ALIAS}"
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5"

FOCUS_INTERVAL="${FOCUS_INTERVAL:-0.2}"
BG_INTERVAL="${BG_INTERVAL:-0.3}"

PRE_NORMAL_SEC="${PRE_NORMAL_SEC:-120}"
RAMP_UP_SEC="${RAMP_UP_SEC:-60}"
HIGH_HOLD_SEC="${HIGH_HOLD_SEC:-300}"
RAMP_DOWN_SEC="${RAMP_DOWN_SEC:-60}"
POST_NORMAL_SEC="${POST_NORMAL_SEC:-120}"

DURATION=$((PRE_NORMAL_SEC + RAMP_UP_SEC + HIGH_HOLD_SEC + RAMP_DOWN_SEC + POST_NORMAL_SEC))

GPU_SMI_INTERVAL="${GPU_SMI_INTERVAL:-1}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-1}"

OUTPUT_ROOT="${OUTPUT_ROOT:-${EXP_RUNS_DIR:-${HOME}/exp_runs}}"
RUN_DIR="${OUTPUT_ROOT}/${RUN_ID}"

mkdir -p \
  "${RUN_DIR}/raw_latency" \
  "${RUN_DIR}/metrics" \
  "${RUN_DIR}/logs" \
  "${RUN_DIR}/thermal" \
  "${RUN_DIR}/k8s" \
  "${RUN_DIR}/dataset"

echo "[INFO] RUN_ID=${RUN_ID}"
echo "[INFO] RUN_DIR=${RUN_DIR}"
echo "[INFO] WORKER_NODE=${WORKER_NODE}"
echo "[INFO] WORKER_IP=${WORKER_IP}"
echo "[INFO] WORKER_SSH=${WORKER_SSH}"
echo "[INFO] DURATION=${DURATION}"

RUN_START_ISO="$(date --iso-8601=seconds)"

cat > "${RUN_DIR}/run_metadata.json" <<META
{
  "run_id": "${RUN_ID}",
  "scenario": "B_thermal_yolo26_3inst",
  "worker_node": "${WORKER_NODE}",
  "worker_ip": "${WORKER_IP}",
  "namespace": "${NS}",
  "run_start_iso": "${RUN_START_ISO}",
  "duration_sec": ${DURATION},
  "focus_interval_sec": ${FOCUS_INTERVAL},
  "bg_interval_sec": ${BG_INTERVAL},
  "phase_plan": [
    {
      "phase": "pre_normal",
      "offset_start_sec": 0,
      "offset_end_sec": ${PRE_NORMAL_SEC},
      "thermal_label": "normal",
      "target_state": "baseline"
    },
    {
      "phase": "ramp_up",
      "offset_start_sec": ${PRE_NORMAL_SEC},
      "offset_end_sec": $((PRE_NORMAL_SEC + RAMP_UP_SEC)),
      "thermal_label": "transition",
      "target_state": "heating"
    },
    {
      "phase": "high_temp_hold",
      "offset_start_sec": $((PRE_NORMAL_SEC + RAMP_UP_SEC)),
      "offset_end_sec": $((PRE_NORMAL_SEC + RAMP_UP_SEC + HIGH_HOLD_SEC)),
      "thermal_label": "thermal_anomaly",
      "target_state": "high_temperature"
    },
    {
      "phase": "ramp_down",
      "offset_start_sec": $((PRE_NORMAL_SEC + RAMP_UP_SEC + HIGH_HOLD_SEC)),
      "offset_end_sec": $((PRE_NORMAL_SEC + RAMP_UP_SEC + HIGH_HOLD_SEC + RAMP_DOWN_SEC)),
      "thermal_label": "transition",
      "target_state": "cooling"
    },
    {
      "phase": "post_normal",
      "offset_start_sec": $((PRE_NORMAL_SEC + RAMP_UP_SEC + HIGH_HOLD_SEC + RAMP_DOWN_SEC)),
      "offset_end_sec": ${DURATION},
      "thermal_label": "recovery",
      "target_state": "post_thermal"
    }
  ]
}
META

echo "[INFO] Save Kubernetes state"

kubectl -n "${NS}" get pods -o wide > "${RUN_DIR}/k8s/pods_before.txt" || true
kubectl describe node "${WORKER_NODE}" > "${RUN_DIR}/k8s/node_${WORKER_NODE}_before.txt" || true
kubectl -n "${NS}" get events --sort-by=.lastTimestamp > "${RUN_DIR}/k8s/events_before.txt" || true

echo "[INFO] Ensure YOLO deployments are running"

kubectl -n "${NS}" scale deploy/yolo26n-focus --replicas=1
kubectl -n "${NS}" scale deploy/yolo26n-bg-1 --replicas=1
kubectl -n "${NS}" scale deploy/yolo26n-bg-2 --replicas=1

kubectl -n "${NS}" rollout status deploy/yolo26n-focus
kubectl -n "${NS}" rollout status deploy/yolo26n-bg-1
kubectl -n "${NS}" rollout status deploy/yolo26n-bg-2

echo "[INFO] Health check"

for port in 18081 18082 18083; do
  curl -sS -o /dev/null \
    --connect-timeout 2 \
    --max-time 5 \
    -w "port=${port} http_code=%{http_code} connect=%{time_connect} total=%{time_total}\n" \
    "http://${WORKER_IP}:${port}/healthz"
done | tee "${RUN_DIR}/logs/pre_healthz.txt"

if [ -n "${TEST_IMAGE:-}" ]; then
  IMAGE_PATH="${TEST_IMAGE}"
else
  IMAGE_PATH="${EXPERIMENT_LAYER_DIR}/yolo26_workload/test_images/sanity_input.png"
fi

if [ ! -f "${IMAGE_PATH}" ]; then
  echo "[ERROR] TEST_IMAGE not found: ${IMAGE_PATH}"
  echo "[HINT] 請先確認 sanity_input.png 存在，或設定 TEST_IMAGE=/path/to/image"
  exit 1
fi

echo "[INFO] IMAGE_PATH=${IMAGE_PATH}"

echo "[INFO] Start GPU telemetry collector on ${WORKER_NODE}"

ssh ${SSH_OPTS} "${WORKER_SSH}" "DURATION=$((DURATION + 30)) INTERVAL=${GPU_SMI_INTERVAL} bash -s" > "${RUN_DIR}/metrics/gpu_smi_${WORKER_NODE}.csv" 2> "${RUN_DIR}/logs/gpu_smi_${WORKER_NODE}.err" <<'EOSSH' &
echo "ts,temperature_gpu_c,power_draw_w,utilization_gpu_pct,utilization_memory_pct,memory_used_mib,memory_total_mib,clocks_sm_mhz,clocks_mem_mhz,pstate"
end=$((SECONDS + DURATION))
while [ "${SECONDS}" -lt "${end}" ]; do
  ts="$(date +"%Y-%m-%dT%H:%M:%S.%N%:z")"
  line="$(nvidia-smi --query-gpu=temperature.gpu,power.draw,utilization.gpu,utilization.memory,memory.used,memory.total,clocks.sm,clocks.mem,pstate --format=csv,noheader,nounits 2>/dev/null | head -n 1)"
  if [ -n "${line}" ]; then
    echo "${ts},${line}"
  else
    echo "${ts},,,,,,,,,"
  fi
  sleep "${INTERVAL}"
done
EOSSH
GPU_SMI_PID=$!

echo "[INFO] GPU telemetry PID=${GPU_SMI_PID}"

echo "[INFO] Start health monitor"

(
  echo "ts,port,http_code,time_connect_s,time_starttransfer_s,time_total_s"
  end=$((SECONDS + DURATION + 30))
  while [ "${SECONDS}" -lt "${end}" ]; do
    ts="$(date +"%Y-%m-%dT%H:%M:%S.%N%:z")"
    for port in 18081 18082 18083; do
      out="$(curl -sS -o /dev/null \
        --connect-timeout 1 \
        --max-time 2 \
        -w "%{http_code},%{time_connect},%{time_starttransfer},%{time_total}" \
        "http://${WORKER_IP}:${port}/healthz" 2>/dev/null || echo "000,0,0,2")"
      echo "${ts},${port},${out}"
    done
    sleep "${HEALTH_INTERVAL}"
  done
) > "${RUN_DIR}/metrics/healthz_ports.csv" 2> "${RUN_DIR}/logs/healthz_monitor.err" &
HEALTH_PID=$!

echo "[INFO] Health monitor PID=${HEALTH_PID}"

# ------------------------------------------------------------
# Multi-node Monitor / VictoriaMetrics Aggregator Collector
# ------------------------------------------------------------
VM_AGGREGATOR_ENABLED="${VM_AGGREGATOR_ENABLED:-1}"
VM_AGGREGATOR_PATH="${VM_AGGREGATOR_PATH:-${MONITORING_DIR}/vm_aggregator.py}"
VM_AGGREGATOR_INTERVAL_SEC="${VM_AGGREGATOR_INTERVAL_SEC:-5}"
VM_AGGREGATOR_OUT="${RUN_DIR}/metrics/vm_aggregator_${WORKER_NODE}.csv"
VM_AGGREGATOR_VM_URL="${VM_AGGREGATOR_VM_URL:-${VM_URL:-}}"
VM_AGGREGATOR_NETDATA_URL="${VM_AGGREGATOR_NETDATA_URL:-${NETDATA_URL:-}}"
VM_AGGREGATOR_NETDATA_CHILD_URL="${VM_AGGREGATOR_NETDATA_CHILD_URL:-${NETDATA_CHILD_URL:-}}"
VM_AGGREGATOR_NETDATA_PARENT_BASE_URL="${VM_AGGREGATOR_NETDATA_PARENT_BASE_URL:-${NETDATA_PARENT_BASE_URL:-}}"
VM_AGGREGATOR_NODE_EXPORTER_INSTANCE="${VM_AGGREGATOR_NODE_EXPORTER_INSTANCE:-${NODE_EXPORTER_INSTANCE:-}}"
if [ -z "${VM_AGGREGATOR_NODE_EXPORTER_INSTANCE}" ] && [ "${WORKER_NODE}" = "icclz1" ]; then
  VM_AGGREGATOR_NODE_EXPORTER_INSTANCE="140.113.179.6:9100"
fi
VM_AGGREGATOR_AUTO_PORT_FORWARD="${VM_AGGREGATOR_AUTO_PORT_FORWARD:-1}"
VM_AGGREGATOR_VM_LOCAL_PORT="${VM_AGGREGATOR_VM_LOCAL_PORT:-18428}"
VM_AGGREGATOR_NETDATA_LOCAL_PORT="${VM_AGGREGATOR_NETDATA_LOCAL_PORT:-11999}"
VM_AGGREGATOR_AUTO_MERGE="${VM_AGGREGATOR_AUTO_MERGE:-1}"
VM_AGGREGATOR_MERGE_TOLERANCE_SEC="${VM_AGGREGATOR_MERGE_TOLERANCE_SEC:-5}"

VM_AGGREGATOR_PID=""
VM_AGGREGATOR_VM_PF_PID=""
VM_AGGREGATOR_NETDATA_PF_PID=""
GPU_SMI_PID=""
HEALTH_PID=""
FOCUS_PID=""
BG1_PID=""
BG2_PID=""
THERMAL_PID=""

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

cleanup_background_jobs() {
  local rc=$?
  trap - EXIT INT TERM

  if [ "${rc}" -ne 0 ]; then
    echo "[INFO] Interrupted or failed; stopping background jobs"
  fi

  kill_tree "${THERMAL_PID}"
  kill_tree "${FOCUS_PID}"
  kill_tree "${BG1_PID}"
  kill_tree "${BG2_PID}"
  kill_tree "${VM_AGGREGATOR_PID}"
  kill_tree "${HEALTH_PID}"
  kill_tree "${GPU_SMI_PID}"
  kill_tree "${VM_AGGREGATOR_VM_PF_PID}"
  kill_tree "${VM_AGGREGATOR_NETDATA_PF_PID}"

  wait "${THERMAL_PID}" >/dev/null 2>&1 || true
  wait "${FOCUS_PID}" >/dev/null 2>&1 || true
  wait "${BG1_PID}" >/dev/null 2>&1 || true
  wait "${BG2_PID}" >/dev/null 2>&1 || true
  wait "${VM_AGGREGATOR_PID}" >/dev/null 2>&1 || true
  wait "${HEALTH_PID}" >/dev/null 2>&1 || true
  wait "${GPU_SMI_PID}" >/dev/null 2>&1 || true
  wait "${VM_AGGREGATOR_VM_PF_PID}" >/dev/null 2>&1 || true
  wait "${VM_AGGREGATOR_NETDATA_PF_PID}" >/dev/null 2>&1 || true

  exit "${rc}"
}

trap cleanup_background_jobs EXIT INT TERM

if [ "${VM_AGGREGATOR_ENABLED}" = "1" ]; then
  echo "[INFO] Start VM aggregator collector"
  echo "[INFO] VM_AGGREGATOR_PATH=${VM_AGGREGATOR_PATH}"
  echo "[INFO] VM_AGGREGATOR_INTERVAL_SEC=${VM_AGGREGATOR_INTERVAL_SEC}"
  echo "[INFO] VM_AGGREGATOR_OUT=${VM_AGGREGATOR_OUT}"
  echo "[INFO] VM_AGGREGATOR_NODE_EXPORTER_INSTANCE=${VM_AGGREGATOR_NODE_EXPORTER_INSTANCE}"

  if [ "${VM_AGGREGATOR_AUTO_PORT_FORWARD}" = "1" ] && [ -z "${VM_AGGREGATOR_VM_URL}" ]; then
    echo "[INFO] Start VM port-forward localhost:${VM_AGGREGATOR_VM_LOCAL_PORT} -> monitoring/victoria-metrics:8428"
    kubectl -n monitoring port-forward \
      svc/vm-victoria-metrics-single-server \
      "${VM_AGGREGATOR_VM_LOCAL_PORT}:8428" \
      > "${RUN_DIR}/logs/vm_aggregator_vm_port_forward.log" 2>&1 &
    VM_AGGREGATOR_VM_PF_PID=$!
    VM_AGGREGATOR_VM_URL="http://127.0.0.1:${VM_AGGREGATOR_VM_LOCAL_PORT}"
  fi

  if [ "${VM_AGGREGATOR_AUTO_PORT_FORWARD}" = "1" ] && [ -z "${VM_AGGREGATOR_NETDATA_PARENT_BASE_URL}" ]; then
    echo "[INFO] Start Netdata port-forward localhost:${VM_AGGREGATOR_NETDATA_LOCAL_PORT} -> netdata/netdata:19999"
    kubectl -n netdata port-forward \
      svc/netdata \
      "${VM_AGGREGATOR_NETDATA_LOCAL_PORT}:19999" \
      > "${RUN_DIR}/logs/vm_aggregator_netdata_port_forward.log" 2>&1 &
    VM_AGGREGATOR_NETDATA_PF_PID=$!
    VM_AGGREGATOR_NETDATA_URL="http://127.0.0.1:${VM_AGGREGATOR_NETDATA_LOCAL_PORT}"
    VM_AGGREGATOR_NETDATA_CHILD_URL="http://127.0.0.1:${VM_AGGREGATOR_NETDATA_LOCAL_PORT}"
    VM_AGGREGATOR_NETDATA_PARENT_BASE_URL="http://127.0.0.1:${VM_AGGREGATOR_NETDATA_LOCAL_PORT}"
  fi

  sleep 2

  python "${EXPERIMENT_LAYER_DIR}/thermal_analysis/collect_vm_aggregator_csv.py" \\
    --aggregator "${VM_AGGREGATOR_PATH}" \
    --out "${VM_AGGREGATOR_OUT}" \
    --seconds "${DURATION}" \
    --interval "${VM_AGGREGATOR_INTERVAL_SEC}" \
    --node "${WORKER_NODE}" \
    --namespace "${NS}" \
    --vm-url "${VM_AGGREGATOR_VM_URL}" \
    --netdata-url "${VM_AGGREGATOR_NETDATA_URL}" \
    --netdata-child-url "${VM_AGGREGATOR_NETDATA_CHILD_URL}" \
    --netdata-parent-base-url "${VM_AGGREGATOR_NETDATA_PARENT_BASE_URL}" \
    --node-exporter-instance "${VM_AGGREGATOR_NODE_EXPORTER_INSTANCE}" \
    > "${RUN_DIR}/logs/vm_aggregator_collector.log" 2>&1 &

  VM_AGGREGATOR_PID=$!
  echo "[INFO] VM aggregator collector PID=${VM_AGGREGATOR_PID}"
fi

echo "[INFO] Start YOLO latency clients"

python "${EXPERIMENT_LAYER_DIR}/thermal_analysis/yolo26_latency_client_stable.py" \\
  --url "http://${WORKER_IP}:18081/infer" \
  --image "${IMAGE_PATH}" \
  --seconds "${DURATION}" \
  --interval "${FOCUS_INTERVAL}" \
  --csv "${RUN_DIR}/raw_latency/focus_inst1_raw.csv" \
  > "${RUN_DIR}/logs/focus_client.log" 2>&1 &
FOCUS_PID=$!

python "${EXPERIMENT_LAYER_DIR}/thermal_analysis/yolo26_latency_client_stable.py" \\
  --url "http://${WORKER_IP}:18082/infer" \
  --image "${IMAGE_PATH}" \
  --seconds "${DURATION}" \
  --interval "${BG_INTERVAL}" \
  --csv "${RUN_DIR}/raw_latency/bg_inst2_raw.csv" \
  > "${RUN_DIR}/logs/bg1_client.log" 2>&1 &
BG1_PID=$!

python "${EXPERIMENT_LAYER_DIR}/thermal_analysis/yolo26_latency_client_stable.py" \\
  --url "http://${WORKER_IP}:18083/infer" \
  --image "${IMAGE_PATH}" \
  --seconds "${DURATION}" \
  --interval "${BG_INTERVAL}" \
  --csv "${RUN_DIR}/raw_latency/bg_inst3_raw.csv" \
  > "${RUN_DIR}/logs/bg2_client.log" 2>&1 &
BG2_PID=$!

echo "[INFO] Client PIDs: focus=${FOCUS_PID}, bg1=${BG1_PID}, bg2=${BG2_PID}"

echo "[INFO] Start delayed thermal command after PRE_NORMAL_SEC=${PRE_NORMAL_SEC}"

if [ -n "${THERMAL_CMD:-}" ]; then
  (
    set +e
    echo "[INFO] thermal command will start after ${PRE_NORMAL_SEC} sec"
    sleep "${PRE_NORMAL_SEC}"
    echo "[INFO] thermal command start at $(date --iso-8601=seconds)"
    echo "[INFO] THERMAL_CMD=${THERMAL_CMD}"
    bash -lc "${THERMAL_CMD}"
    rc=$?
    echo "[INFO] thermal command exit_code=${rc} at $(date --iso-8601=seconds)"
    exit "${rc}"
  ) > "${RUN_DIR}/thermal/thermal_cmd.log" 2>&1 &
  THERMAL_PID=$!
  echo "[INFO] Thermal command PID=${THERMAL_PID}"
else
  echo "[WARN] THERMAL_CMD is empty. This run will collect YOLO + metrics only, without active thermal injection." | tee "${RUN_DIR}/thermal/thermal_cmd.log"
  THERMAL_PID=""
fi

set +e
wait "${FOCUS_PID}"; FOCUS_RC=$?
wait "${BG1_PID}"; BG1_RC=$?
wait "${BG2_PID}"; BG2_RC=$?
set -e

echo "[INFO] Client exit codes: focus=${FOCUS_RC}, bg1=${BG1_RC}, bg2=${BG2_RC}" | tee "${RUN_DIR}/logs/client_exit_codes.txt"

if [ -n "${THERMAL_PID}" ]; then
  set +e
  wait "${THERMAL_PID}"
  THERMAL_RC=$?
  set -e
  echo "[INFO] Thermal command exit code=${THERMAL_RC}" | tee "${RUN_DIR}/thermal/thermal_exit_code.txt"
fi

if [ -n "${VM_AGGREGATOR_PID:-}" ]; then
  set +e
  wait "${VM_AGGREGATOR_PID}"
  VM_AGGREGATOR_RC=$?
  set -e
  echo "[INFO] VM aggregator collector exit code=${VM_AGGREGATOR_RC}" | tee "${RUN_DIR}/logs/vm_aggregator_exit_code.txt"
fi

if [ -n "${VM_AGGREGATOR_VM_PF_PID:-}" ]; then
  kill "${VM_AGGREGATOR_VM_PF_PID}" >/dev/null 2>&1 || true
  wait "${VM_AGGREGATOR_VM_PF_PID}" >/dev/null 2>&1 || true
fi

if [ -n "${VM_AGGREGATOR_NETDATA_PF_PID:-}" ]; then
  kill "${VM_AGGREGATOR_NETDATA_PF_PID}" >/dev/null 2>&1 || true
  wait "${VM_AGGREGATOR_NETDATA_PF_PID}" >/dev/null 2>&1 || true
fi

sleep 3

kubectl -n "${NS}" get pods -o wide > "${RUN_DIR}/k8s/pods_after.txt" || true
kubectl describe node "${WORKER_NODE}" > "${RUN_DIR}/k8s/node_${WORKER_NODE}_after.txt" || true
kubectl -n "${NS}" get events --sort-by=.lastTimestamp > "${RUN_DIR}/k8s/events_after.txt" || true

echo "[INFO] Run outage labeling"

python "${EXPERIMENT_LAYER_DIR}/thermal_analysis/detect_service_outage.py" \\
  --run-dir "${RUN_DIR}" \
  --window-sec 5 \
  --min-instances 2 \
  --min-failures 2 \
  --merge-gap-sec 5 \
  --buffer-sec 10 \
  --latency-degraded-ms 1000 \
  --min-clean-segment-sec 60 \
  > "${RUN_DIR}/logs/outage_labeling.log" 2>&1 || true

if [ "${VM_AGGREGATOR_ENABLED}" = "1" ] && [ "${VM_AGGREGATOR_AUTO_MERGE}" = "1" ]; then
  echo "[INFO] Merge VM aggregator metrics into labeled dataset"
  python "${EXPERIMENT_LAYER_DIR}/thermal_analysis/merge_vmagg_into_thermal_dataset.py" \\
    --run-dir "${RUN_DIR}" \
    --vmagg-csv "${VM_AGGREGATOR_OUT}" \
    --tolerance-sec "${VM_AGGREGATOR_MERGE_TOLERANCE_SEC}" \
    > "${RUN_DIR}/logs/vm_aggregator_merge.log" 2>&1 || {
      echo "[WARN] VM aggregator merge failed; see ${RUN_DIR}/logs/vm_aggregator_merge.log"
    }
fi

echo "[INFO] Done: ${RUN_DIR}"
