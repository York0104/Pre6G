#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUN_ID="${1:-r2_evictionhard_short_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}/results/${RUN_ID}}"
GENERATED_DIR="${OUT_DIR}/generated"
STATE_FILE="${STATE_FILE:-${OUT_DIR}/current_phase.json}"
TARGET_NODE="${TARGET_NODE:-icclz1}"
TARGET_HOST="${TARGET_HOST:-100.105.48.97}"
TARGET_SSH_HOST="${TARGET_SSH_HOST:-${TARGET_NODE}}"
NAMESPACE="${NAMESPACE:-intent-lab}"
MODE="${MODE:-prepare}"
APPLY_EVICTION_HARD="${APPLY_EVICTION_HARD:-0}"
RUN_EXPERIMENT="${RUN_EXPERIMENT:-0}"
ROLLBACK_ON_FAILURE="${ROLLBACK_ON_FAILURE:-0}"
SKIP_REMOTE_PRECHECK="${SKIP_REMOTE_PRECHECK:-0}"
SKIP_CLUSTER_PRECHECK="${SKIP_CLUSTER_PRECHECK:-0}"
PROBE_DRAIN_TIMEOUT_SECONDS="${PROBE_DRAIN_TIMEOUT_SECONDS:-45}"
METRICS_URL="${METRICS_URL:-http://${TARGET_HOST}:9100/metrics}"
FINAL_STATE_STATUS="${FINAL_STATE_STATUS:-}"

EVICTION_HARD_VALUE="${EVICTION_HARD_VALUE:-memory.available<2Gi,nodefs.available<10%,imagefs.available<15%}"
MEM_AVAILABLE_SAMPLES="${MEM_AVAILABLE_SAMPLES:-5}"
TARGET_REMAIN_MIB="${TARGET_REMAIN_MIB:-1536}"
PER_POD_VM_MIB="${PER_POD_VM_MIB:-2600}"
MEM_AGG_H_VM_EXTRA_MIB="${MEM_AGG_H_VM_EXTRA_MIB:-256}"
MEM_AGG_H_PARALLELISM_EXTRA="${MEM_AGG_H_PARALLELISM_EXTRA:-1}"
PER_POD_REQUEST_MEMORY="${PER_POD_REQUEST_MEMORY:-256Mi}"
PER_POD_LIMIT_MEMORY="${PER_POD_LIMIT_MEMORY:-3Gi}"
PER_POD_REQUEST_CPU="${PER_POD_REQUEST_CPU:-100m}"
PER_POD_LIMIT_CPU="${PER_POD_LIMIT_CPU:-500m}"
PARALLELISM_MIN="${PARALLELISM_MIN:-2}"
PARALLELISM_MAX="${PARALLELISM_MAX:-24}"
STRESS_PRIORITY_CLASS="${STRESS_PRIORITY_CLASS:-device-availability-stress-low}"
STRESS_IMAGE="${STRESS_IMAGE:-polinux/stress:latest}"
CPU_STRESS_IMAGE="${CPU_STRESS_IMAGE:-polinux/stress:latest}"
MIX_CPU_WORKERS_PER_POD="${MIX_CPU_WORKERS_PER_POD:-1}"

BASELINE_SECONDS="${BASELINE_SECONDS:-600}"
MEM_AGG_M_SECONDS="${MEM_AGG_M_SECONDS:-1200}"
RECOVERY_1_SECONDS="${RECOVERY_1_SECONDS:-600}"
MEM_AGG_H_SECONDS="${MEM_AGG_H_SECONDS:-1500}"
RECOVERY_2_SECONDS="${RECOVERY_2_SECONDS:-600}"
MIX_AGG_M_SECONDS="${MIX_AGG_M_SECONDS:-900}"
FINAL_RECOVERY_SECONDS="${FINAL_RECOVERY_SECONDS:-600}"

mkdir -p "${OUT_DIR}" "${GENERATED_DIR}"

echo "[INFO] RUN_ID=${RUN_ID}"
echo "[INFO] OUT_DIR=${OUT_DIR}"
echo "[INFO] TARGET_NODE=${TARGET_NODE}"
echo "[INFO] TARGET_SSH_HOST=${TARGET_SSH_HOST}"
echo "[INFO] NAMESPACE=${NAMESPACE}"
echo "[INFO] MODE=${MODE}"
echo "[INFO] APPLY_EVICTION_HARD=${APPLY_EVICTION_HARD}"
echo "[INFO] RUN_EXPERIMENT=${RUN_EXPERIMENT}"
echo "[INFO] SKIP_REMOTE_PRECHECK=${SKIP_REMOTE_PRECHECK}"
echo "[INFO] SKIP_CLUSTER_PRECHECK=${SKIP_CLUSTER_PRECHECK}"
echo "[INFO] EVICTION_HARD_VALUE=${EVICTION_HARD_VALUE}"

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

remote_cmd() {
  ssh "${TARGET_SSH_HOST}" "$@"
}

capture_node_snapshot() {
  local prefix="$1"
  if [[ "${SKIP_CLUSTER_PRECHECK}" == "1" ]]; then
    echo "[INFO] skipping cluster node snapshot for ${prefix}" > "${OUT_DIR}/${prefix}_cluster_skipped.log"
    return
  fi
  kubectl get node "${TARGET_NODE}" -o wide > "${OUT_DIR}/${prefix}_wide.txt" || true
  kubectl describe node "${TARGET_NODE}" > "${OUT_DIR}/${prefix}_describe.log" || true
  kubectl get node "${TARGET_NODE}" -o json > "${OUT_DIR}/${prefix}.json" || true
}

capture_k8s_snapshot() {
  local prefix="$1"
  if [[ "${SKIP_CLUSTER_PRECHECK}" == "1" ]]; then
    echo "[INFO] skipping cluster namespace snapshot for ${prefix}" > "${OUT_DIR}/${prefix}_namespace_skipped.log"
    return
  fi
  kubectl -n "${NAMESPACE}" get pods -o wide > "${OUT_DIR}/${prefix}_pods.txt" || true
  kubectl -n "${NAMESPACE}" get ds -o wide > "${OUT_DIR}/${prefix}_daemonsets.txt" || true
  kubectl -n "${NAMESPACE}" get jobs -o wide > "${OUT_DIR}/${prefix}_jobs.txt" || true
}

capture_remote_snapshot() {
  local prefix="$1"
  if [[ "${SKIP_REMOTE_PRECHECK}" == "1" ]]; then
    echo "[INFO] skipping remote snapshot for ${prefix}" > "${OUT_DIR}/${prefix}_remote_skipped.log"
    return
  fi
  remote_cmd 'systemctl cat k3s-agent' > "${OUT_DIR}/${prefix}_k3s_agent_unit.txt" || true
  remote_cmd 'sudo cat /etc/rancher/k3s/config.yaml 2>/dev/null || true' > "${OUT_DIR}/${prefix}_k3s_config.yaml" || true
}

capture_final_logs() {
  if [[ "${SKIP_CLUSTER_PRECHECK}" == "1" ]]; then
    echo "[INFO] cluster pod describe skipped" > "${OUT_DIR}/cluster_logs_skipped.log"
  else
    kubectl -n "${NAMESPACE}" describe pod -l app=node-sentinel > "${OUT_DIR}/sentinel_pod_describe.log" 2>&1 || true
  fi
  if [[ "${SKIP_REMOTE_PRECHECK}" == "1" ]]; then
    echo "[INFO] remote log collection skipped" > "${OUT_DIR}/remote_logs_skipped.log"
    return
  fi
  remote_cmd 'journalctl -u k3s-agent --since "8 hours ago" --no-pager' > "${OUT_DIR}/k3s_agent_journal.log" || true
  remote_cmd 'journalctl -u containerd --since "8 hours ago" --no-pager' > "${OUT_DIR}/containerd_journal.log" || true
  remote_cmd 'journalctl -k --since "8 hours ago" --no-pager | grep -i -E "oom|killed|memory|evict|pressure" || true' > "${OUT_DIR}/kernel_oom_events.log" || true
}

stop_watchers() {
  for pid_var in NODE_WATCH_PID POD_WATCH_PID EVENT_WATCH_PID; do
    local pid="${!pid_var:-}"
    if [[ -n "${pid}" ]]; then
      kill "${pid}" 2>/dev/null || true
      wait "${pid}" 2>/dev/null || true
    fi
  done
}

cleanup_phase_jobs() {
  if [[ "${SKIP_CLUSTER_PRECHECK}" == "1" ]]; then
    return
  fi
  kubectl -n "${NAMESPACE}" delete job device-avail-r2-mem-agg device-avail-r2-mix-agg-cpu --ignore-not-found=true >/dev/null 2>&1 || true
}

backup_k3s_config() {
  if [[ "${SKIP_REMOTE_PRECHECK}" == "1" ]]; then
    return
  fi
  remote_cmd 'sudo mkdir -p /etc/rancher/k3s/backup-device-availability'
  remote_cmd 'sudo cp -a /etc/rancher/k3s/config.yaml /etc/rancher/k3s/backup-device-availability/config.yaml.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true'
}

sample_mem_available_kib() {
  if [[ -n "${MEM_AVAILABLE_KIB_OVERRIDE:-}" ]]; then
    echo "${MEM_AVAILABLE_KIB_OVERRIDE}"
    return
  fi
  if [[ "${SKIP_REMOTE_PRECHECK}" == "1" ]]; then
    local metric_value
    metric_value="$(curl -fsS "${METRICS_URL}" 2>/dev/null | awk '/^node_memory_MemAvailable_bytes / {print $2; exit}')"
    if [[ -n "${metric_value}" ]]; then
      python3 - <<'PY' "${metric_value}"
import sys
value=float(sys.argv[1])
print(int(value/1024))
PY
      return
    fi
  fi
  if [[ "${SKIP_REMOTE_PRECHECK}" == "1" ]]; then
    echo "8388608"
    return
  fi

  local sample_count=0
  local sum=0
  while [[ "${sample_count}" -lt "${MEM_AVAILABLE_SAMPLES}" ]]; do
    local value
    value="$(remote_cmd "awk '/MemAvailable/ {print \$2}' /proc/meminfo" | tr -d '\r' | tail -n 1)"
    if [[ -n "${value}" ]]; then
      sum=$((sum + value))
      sample_count=$((sample_count + 1))
    fi
    sleep 1
  done
  echo $((sum / sample_count))
}

derive_pressure_profile() {
  MEM_AVAILABLE_BASE_KIB="$(sample_mem_available_kib)"
  TARGET_REMAIN_KIB=$((TARGET_REMAIN_MIB * 1024))
  PER_POD_VM_KIB=$((PER_POD_VM_MIB * 1024))

  TARGET_AGGREGATE_VM_KIB=$((MEM_AVAILABLE_BASE_KIB - TARGET_REMAIN_KIB))
  AGGREGATE_VM_KIB="${TARGET_AGGREGATE_VM_KIB}"
  local min_agg_kib=$((2 * PER_POD_VM_KIB))
  if [[ "${AGGREGATE_VM_KIB}" -lt "${min_agg_kib}" ]]; then
    AGGREGATE_VM_KIB="${min_agg_kib}"
  fi
  local max_agg_kib=$((PARALLELISM_MAX * PER_POD_VM_KIB))
  PRESSURE_PROFILE_STATUS="target_reachable"
  if [[ "${AGGREGATE_VM_KIB}" -gt "${max_agg_kib}" ]]; then
    AGGREGATE_VM_KIB="${max_agg_kib}"
    PRESSURE_PROFILE_STATUS="capped_by_parallelism_max"
  fi

  PARALLELISM=$(((AGGREGATE_VM_KIB + PER_POD_VM_KIB - 1) / PER_POD_VM_KIB))
  if [[ "${PARALLELISM}" -lt "${PARALLELISM_MIN}" ]]; then
    PARALLELISM="${PARALLELISM_MIN}"
  fi
  if [[ "${PARALLELISM}" -gt "${PARALLELISM_MAX}" ]]; then
    PARALLELISM="${PARALLELISM_MAX}"
  fi

  MEM_AGG_M_PARALLELISM=$((PARALLELISM > PARALLELISM_MIN ? PARALLELISM - 1 : PARALLELISM_MIN))
  MEM_AGG_H_PARALLELISM=$((PARALLELISM + MEM_AGG_H_PARALLELISM_EXTRA))
  if [[ "${MEM_AGG_H_PARALLELISM}" -gt "${PARALLELISM_MAX}" ]]; then
    MEM_AGG_H_PARALLELISM="${PARALLELISM_MAX}"
  fi
  MIX_AGG_M_PARALLELISM=$((PARALLELISM > 2 ? PARALLELISM - 1 : 2))

  MEM_AGG_M_VM_MIB=$((PER_POD_VM_MIB - 256))
  if [[ "${MEM_AGG_M_VM_MIB}" -lt 1536 ]]; then
    MEM_AGG_M_VM_MIB=1536
  fi
  MEM_AGG_H_VM_MIB=$((PER_POD_VM_MIB + MEM_AGG_H_VM_EXTRA_MIB))
  local per_pod_limit_mib
  per_pod_limit_mib="$(python3 - <<'PY' "${PER_POD_LIMIT_MEMORY}"
import re, sys
value=sys.argv[1].strip()
match=re.fullmatch(r'(\d+)([KMG]i?)?', value)
if not match:
    print(0)
    raise SystemExit
num=int(match.group(1))
unit=match.group(2) or ''
factors={'':1/1048576,'Ki':1/1024,'Mi':1,'Gi':1024,'K':1/1024,'M':1,'G':1000}
print(int(num*factors[unit]))
PY
)"
  if [[ "${per_pod_limit_mib}" -gt 0 ]]; then
    local max_safe_vm_mib=$((per_pod_limit_mib - 128))
    if [[ "${MEM_AGG_H_VM_MIB}" -gt "${max_safe_vm_mib}" ]]; then
      MEM_AGG_H_VM_MIB="${max_safe_vm_mib}"
    fi
  fi
  MIX_AGG_M_VM_MIB=$((PER_POD_VM_MIB - 128))
  if [[ "${MIX_AGG_M_VM_MIB}" -lt 1536 ]]; then
    MIX_AGG_M_VM_MIB=1536
  fi
}

generate_eviction_config() {
  cat > "${GENERATED_DIR}/r2-eviction-hard-config.yaml" <<EOF
kubelet-arg:
  - "eviction-hard=${EVICTION_HARD_VALUE}"
EOF

  cat > "${GENERATED_DIR}/apply_eviction_hard.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

ssh ${TARGET_SSH_HOST@Q} 'sudo mkdir -p /etc/rancher/k3s/backup-device-availability'
ssh ${TARGET_SSH_HOST@Q} 'sudo cp -a /etc/rancher/k3s/config.yaml /etc/rancher/k3s/backup-device-availability/config.yaml.\$(date +%Y%m%d_%H%M%S) 2>/dev/null || true'
echo 'Merge the following fragment into /etc/rancher/k3s/config.yaml on ${TARGET_SSH_HOST}:'
cat ${GENERATED_DIR@Q}/r2-eviction-hard-config.yaml
echo 'Then run: sudo systemctl restart k3s-agent'
EOF
  chmod +x "${GENERATED_DIR}/apply_eviction_hard.sh"

  cat > "${GENERATED_DIR}/rollback_eviction_hard.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

echo 'Restore the previous /etc/rancher/k3s/config.yaml backup on ${TARGET_SSH_HOST}, then run:'
echo 'sudo systemctl restart k3s-agent'
EOF
  chmod +x "${GENERATED_DIR}/rollback_eviction_hard.sh"
}

generate_mem_job_manifest() {
  local output_path="$1"
  local job_name="$2"
  local parallelism="$3"
  local vm_mib="$4"
  local phase_name="$5"
  cat > "${output_path}" <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
  namespace: ${NAMESPACE}
  labels:
    app: ${job_name}
    device-availability-phase: ${phase_name}
spec:
  backoffLimit: 0
  completions: ${parallelism}
  parallelism: ${parallelism}
  ttlSecondsAfterFinished: 60
  template:
    metadata:
      labels:
        app: ${job_name}
        device-availability-phase: ${phase_name}
    spec:
      restartPolicy: Never
      priorityClassName: ${STRESS_PRIORITY_CLASS}
      nodeSelector:
        kubernetes.io/hostname: ${TARGET_NODE}
      containers:
      - name: stress
        image: ${STRESS_IMAGE}
        command: ["stress"]
        args: ["--vm", "1", "--vm-bytes", "${vm_mib}M", "--vm-keep"]
        resources:
          requests:
            cpu: "${PER_POD_REQUEST_CPU}"
            memory: "${PER_POD_REQUEST_MEMORY}"
          limits:
            cpu: "${PER_POD_LIMIT_CPU}"
            memory: "${PER_POD_LIMIT_MEMORY}"
EOF
}

generate_mix_job_manifest() {
  local output_path="$1"
  local mem_parallelism="$2"
  local vm_mib="$3"
  cat > "${output_path}" <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: device-avail-r2-mem-agg
  namespace: ${NAMESPACE}
  labels:
    app: device-avail-r2-mem-agg
    device-availability-phase: MIX-AGG-M
spec:
  backoffLimit: 0
  completions: ${mem_parallelism}
  parallelism: ${mem_parallelism}
  ttlSecondsAfterFinished: 60
  template:
    metadata:
      labels:
        app: device-avail-r2-mem-agg
        device-availability-phase: MIX-AGG-M
    spec:
      restartPolicy: Never
      priorityClassName: ${STRESS_PRIORITY_CLASS}
      nodeSelector:
        kubernetes.io/hostname: ${TARGET_NODE}
      containers:
      - name: stress
        image: ${STRESS_IMAGE}
        command: ["stress"]
        args: ["--vm", "1", "--vm-bytes", "${vm_mib}M", "--vm-keep"]
        resources:
          requests:
            cpu: "${PER_POD_REQUEST_CPU}"
            memory: "${PER_POD_REQUEST_MEMORY}"
          limits:
            cpu: "${PER_POD_LIMIT_CPU}"
            memory: "${PER_POD_LIMIT_MEMORY}"
---
apiVersion: batch/v1
kind: Job
metadata:
  name: device-avail-r2-mix-agg-cpu
  namespace: ${NAMESPACE}
  labels:
    app: device-avail-r2-mix-agg-cpu
    device-availability-phase: MIX-AGG-M
spec:
  backoffLimit: 0
  completions: ${mem_parallelism}
  parallelism: ${mem_parallelism}
  ttlSecondsAfterFinished: 60
  template:
    metadata:
      labels:
        app: device-avail-r2-mix-agg-cpu
        device-availability-phase: MIX-AGG-M
    spec:
      restartPolicy: Never
      priorityClassName: ${STRESS_PRIORITY_CLASS}
      nodeSelector:
        kubernetes.io/hostname: ${TARGET_NODE}
      containers:
      - name: stress
        image: ${CPU_STRESS_IMAGE}
        command: ["stress"]
        args: ["--cpu", "${MIX_CPU_WORKERS_PER_POD}"]
        resources:
          requests:
            cpu: "${PER_POD_REQUEST_CPU}"
            memory: "${PER_POD_REQUEST_MEMORY}"
          limits:
            cpu: "${PER_POD_LIMIT_CPU}"
            memory: "${PER_POD_LIMIT_MEMORY}"
EOF
}

generate_manifests() {
  generate_eviction_config
  generate_mem_job_manifest "${GENERATED_DIR}/r2-mem-agg-m.yaml" "device-avail-r2-mem-agg" "${MEM_AGG_M_PARALLELISM}" "${MEM_AGG_M_VM_MIB}" "MEM-AGG-M"
  generate_mem_job_manifest "${GENERATED_DIR}/r2-mem-agg-h.yaml" "device-avail-r2-mem-agg" "${MEM_AGG_H_PARALLELISM}" "${MEM_AGG_H_VM_MIB}" "MEM-AGG-H"
  generate_mix_job_manifest "${GENERATED_DIR}/r2-mix-agg-m.yaml" "${MIX_AGG_M_PARALLELISM}" "${MIX_AGG_M_VM_MIB}"
}

write_profile_summary() {
  cat > "${OUT_DIR}/r2_profile_summary.env" <<EOF
RUN_ID=${RUN_ID}
MODE=${MODE}
TARGET_NODE=${TARGET_NODE}
TARGET_SSH_HOST=${TARGET_SSH_HOST}
EVICTION_HARD_VALUE=${EVICTION_HARD_VALUE}
MEM_AVAILABLE_BASE_KIB=${MEM_AVAILABLE_BASE_KIB}
TARGET_REMAIN_KIB=${TARGET_REMAIN_KIB}
TARGET_AGGREGATE_VM_KIB=${TARGET_AGGREGATE_VM_KIB}
AGGREGATE_VM_KIB=${AGGREGATE_VM_KIB}
PER_POD_VM_MIB=${PER_POD_VM_MIB}
MEM_AGG_H_VM_EXTRA_MIB=${MEM_AGG_H_VM_EXTRA_MIB}
MEM_AGG_H_PARALLELISM_EXTRA=${MEM_AGG_H_PARALLELISM_EXTRA}
PARALLELISM=${PARALLELISM}
PRESSURE_PROFILE_STATUS=${PRESSURE_PROFILE_STATUS}
MEM_AGG_M_PARALLELISM=${MEM_AGG_M_PARALLELISM}
MEM_AGG_H_PARALLELISM=${MEM_AGG_H_PARALLELISM}
MIX_AGG_M_PARALLELISM=${MIX_AGG_M_PARALLELISM}
MEM_AGG_M_VM_MIB=${MEM_AGG_M_VM_MIB}
MEM_AGG_H_VM_MIB=${MEM_AGG_H_VM_MIB}
MIX_AGG_M_VM_MIB=${MIX_AGG_M_VM_MIB}
EOF
}

write_report_stub() {
  cat > "${OUT_DIR}/report_stub.md" <<EOF
# R2 evictionHard Short Validation Stub

- run_id: \`${RUN_ID}\`
- target_node: \`${TARGET_NODE}\`
- mode: \`${MODE}\`
- evictionHard: \`${EVICTION_HARD_VALUE}\`
- mem_available_base_kib: \`${MEM_AVAILABLE_BASE_KIB}\`
- target_aggregate_vm_kib: \`${TARGET_AGGREGATE_VM_KIB}\`
- aggregate_vm_kib: \`${AGGREGATE_VM_KIB}\`
- per_pod_vm_mib: \`${PER_POD_VM_MIB}\`
- parallelism: \`${PARALLELISM}\`
- pressure_profile_status: \`${PRESSURE_PROFILE_STATUS}\`

Generated manifests:

- \`generated/r2-eviction-hard-config.yaml\`
- \`generated/r2-mem-agg-m.yaml\`
- \`generated/r2-mem-agg-h.yaml\`
- \`generated/r2-mix-agg-m.yaml\`

Interpretation:

- if \`pressure_profile_status=capped_by_parallelism_max\`, the current profile is likely too conservative to actually reach the eviction threshold on this node
EOF
}

apply_eviction_config() {
  backup_k3s_config
  echo "[WARN] automatic config merge is intentionally not performed"
  echo "[WARN] use ${GENERATED_DIR}/apply_eviction_hard.sh and ${GENERATED_DIR}/rollback_eviction_hard.sh as operator helpers"
}

run_experiment_phase() {
  local phase_name="$1"
  local duration_seconds="$2"
  local manifest_path="${3:-}"
  write_final_state "${phase_name}"
  cleanup_phase_jobs
  echo "[INFO] phase=${phase_name} duration=${duration_seconds}s"
  if [[ -n "${manifest_path}" ]]; then
    kubectl apply -f "${manifest_path}"
  fi
  sleep "${duration_seconds}"
}

stop_probe_if_needed() {
  if [[ -n "${PROBE_PID:-}" ]]; then
    kill "${PROBE_PID}" 2>/dev/null || true
    wait "${PROBE_PID}" 2>/dev/null || true
  fi
}

cleanup() {
  local signal_name="${1:-EXIT}"
  cleanup_phase_jobs
  stop_watchers
  stop_probe_if_needed
  capture_k8s_snapshot "after"
  capture_node_snapshot "node_after"
  capture_remote_snapshot "after"
  capture_final_logs
  if [[ -n "${FINAL_STATE_STATUS}" ]]; then
    write_final_state "${FINAL_STATE_STATUS}"
  elif [[ "${signal_name}" != "EXIT" ]]; then
    write_final_state "INTERRUPTED"
  fi
}

trap 'cleanup EXIT' EXIT
trap 'cleanup INT; exit 130' INT
trap 'cleanup TERM; exit 143' TERM

capture_node_snapshot "node_before"
capture_k8s_snapshot "before"
capture_remote_snapshot "before"

if [[ "${SKIP_CLUSTER_PRECHECK}" != "1" ]]; then
  kubectl get node "${TARGET_NODE}" -w > "${OUT_DIR}/node_watch.log" 2>&1 &
  NODE_WATCH_PID=$!
  kubectl -n "${NAMESPACE}" get pods -o wide -w > "${OUT_DIR}/pod_watch.log" 2>&1 &
  POD_WATCH_PID=$!
  kubectl -n "${NAMESPACE}" get events --watch > "${OUT_DIR}/k8s_events_watch.log" 2>&1 &
  EVENT_WATCH_PID=$!
fi

derive_pressure_profile
generate_manifests
write_profile_summary
write_report_stub

if [[ "${APPLY_EVICTION_HARD}" == "1" ]]; then
  apply_eviction_config
fi

if [[ "${RUN_EXPERIMENT}" != "1" ]]; then
  FINAL_STATE_STATUS="PREPARED"
  echo "[INFO] preparation complete; manifests and preflight evidence are ready in ${OUT_DIR}"
  exit 0
fi

python3 "${SCRIPT_DIR}/availability_probe.py" \
  --target-node "${TARGET_NODE}" \
  --target-host "${TARGET_HOST}" \
  --metrics-url "${METRICS_URL}" \
  --interval-seconds 5 \
  --phase-file "${STATE_FILE}" \
  --stop-phase-name COMPLETE \
  --out-dir "${OUT_DIR}" &
PROBE_PID=$!

run_experiment_phase "BASELINE" "${BASELINE_SECONDS}"
run_experiment_phase "MEM-AGG-M" "${MEM_AGG_M_SECONDS}" "${GENERATED_DIR}/r2-mem-agg-m.yaml"
run_experiment_phase "RECOVERY-1" "${RECOVERY_1_SECONDS}"
run_experiment_phase "MEM-AGG-H" "${MEM_AGG_H_SECONDS}" "${GENERATED_DIR}/r2-mem-agg-h.yaml"
run_experiment_phase "RECOVERY-2" "${RECOVERY_2_SECONDS}"
run_experiment_phase "MIX-AGG-M" "${MIX_AGG_M_SECONDS}" "${GENERATED_DIR}/r2-mix-agg-m.yaml"
run_experiment_phase "FINAL-RECOVERY" "${FINAL_RECOVERY_SECONDS}"

FINAL_STATE_STATUS="COMPLETE"
write_final_state "COMPLETE"
for ((i=0; i<PROBE_DRAIN_TIMEOUT_SECONDS; i++)); do
  if ! kill -0 "${PROBE_PID}" 2>/dev/null; then
    break
  fi
  sleep 1
done
if kill -0 "${PROBE_PID}" 2>/dev/null; then
  echo "[WARN] probe did not exit within ${PROBE_DRAIN_TIMEOUT_SECONDS}s after experiment completion; stopping probe"
  kill "${PROBE_PID}" 2>/dev/null || true
fi
wait "${PROBE_PID}" || true

trap - EXIT
cleanup EXIT
echo "[INFO] R2 evictionHard short validation completed"
