#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUN_ID="${1:-device_availability_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${SCRIPT_DIR}/results/${RUN_ID}}"
STATE_FILE="${STATE_FILE:-${OUT_DIR}/current_phase.json}"
TIMELINE_FILE="${TIMELINE_FILE:-${OUT_DIR}/phase_timeline.jsonl}"
TARGET_NODE="${TARGET_NODE:-icclz1}"
NAMESPACE="${NAMESPACE:-intent-lab}"
CPU_IMAGE="${CPU_IMAGE:-polinux/stress:latest}"
MEM_IMAGE="${MEM_IMAGE:-polinux/stress:latest}"
EXPERIMENT_PROFILE="${EXPERIMENT_PROFILE:-full_6h}"
STRESS_PRIORITY_CLASS="${STRESS_PRIORITY_CLASS:-}"
CPU_STRESS_REQUEST_CPU="${CPU_STRESS_REQUEST_CPU:-}"
CPU_STRESS_LIMIT_CPU="${CPU_STRESS_LIMIT_CPU:-}"
CPU_STRESS_REQUEST_MEMORY="${CPU_STRESS_REQUEST_MEMORY:-}"
CPU_STRESS_LIMIT_MEMORY="${CPU_STRESS_LIMIT_MEMORY:-}"
MEM_STRESS_REQUEST_CPU="${MEM_STRESS_REQUEST_CPU:-}"
MEM_STRESS_LIMIT_CPU="${MEM_STRESS_LIMIT_CPU:-}"
MEM_STRESS_REQUEST_MEMORY="${MEM_STRESS_REQUEST_MEMORY:-}"
MEM_STRESS_LIMIT_MEMORY="${MEM_STRESS_LIMIT_MEMORY:-}"

mkdir -p "${OUT_DIR}"

write_phase_state() {
  local phase_name="$1"
  local cpu_load_percent="$2"
  local memory_size_percent="$3"
  local duration_seconds="$4"
  cat > "${STATE_FILE}" <<EOF
{
  "phase_name": "${phase_name}",
  "cpu_load_percent": ${cpu_load_percent},
  "memory_size_percent": ${memory_size_percent},
  "duration_seconds": ${duration_seconds},
  "target_node": "${TARGET_NODE}",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
  printf '{"timestamp":"%s","phase_name":"%s","cpu_load_percent":%s,"memory_size_percent":%s,"duration_seconds":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "${phase_name}" \
    "${cpu_load_percent}" \
    "${memory_size_percent}" \
    "${duration_seconds}" >> "${TIMELINE_FILE}"
}

delete_stress_jobs() {
  kubectl -n "${NAMESPACE}" delete job device-avail-cpu-stress --ignore-not-found=true >/dev/null
  kubectl -n "${NAMESPACE}" delete job device-avail-mem-stress --ignore-not-found=true >/dev/null
}

build_priority_block() {
  if [[ -n "${STRESS_PRIORITY_CLASS}" ]]; then
    printf '      priorityClassName: %s\n' "${STRESS_PRIORITY_CLASS}"
  fi
}

build_resource_block() {
  local request_cpu="$1"
  local limit_cpu="$2"
  local request_memory="$3"
  local limit_memory="$4"

  if [[ -z "${request_cpu}" && -z "${limit_cpu}" && -z "${request_memory}" && -z "${limit_memory}" ]]; then
    return
  fi

  printf '        resources:\n'
  if [[ -n "${request_cpu}" || -n "${request_memory}" ]]; then
    printf '          requests:\n'
    if [[ -n "${request_cpu}" ]]; then
      printf '            cpu: "%s"\n' "${request_cpu}"
    fi
    if [[ -n "${request_memory}" ]]; then
      printf '            memory: "%s"\n' "${request_memory}"
    fi
  fi
  if [[ -n "${limit_cpu}" || -n "${limit_memory}" ]]; then
    printf '          limits:\n'
    if [[ -n "${limit_cpu}" ]]; then
      printf '            cpu: "%s"\n' "${limit_cpu}"
    fi
    if [[ -n "${limit_memory}" ]]; then
      printf '            memory: "%s"\n' "${limit_memory}"
    fi
  fi
}

apply_cpu_job() {
  local workers="$1"
  local priority_block
  local resource_block
  priority_block="$(build_priority_block)"
  resource_block="$(build_resource_block "${CPU_STRESS_REQUEST_CPU}" "${CPU_STRESS_LIMIT_CPU}" "${CPU_STRESS_REQUEST_MEMORY}" "${CPU_STRESS_LIMIT_MEMORY}")"
  cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: device-avail-cpu-stress
  namespace: ${NAMESPACE}
spec:
  ttlSecondsAfterFinished: 60
  template:
    spec:
      restartPolicy: Never
      nodeSelector:
        kubernetes.io/hostname: ${TARGET_NODE}
${priority_block}
      containers:
      - name: stress
        image: ${CPU_IMAGE}
        command: ["stress"]
        args: ["--cpu", "${workers}"]
${resource_block}
EOF
}

apply_mem_job() {
  local workers="$1"
  local vm_bytes="$2"
  local priority_block
  local resource_block
  priority_block="$(build_priority_block)"
  resource_block="$(build_resource_block "${MEM_STRESS_REQUEST_CPU}" "${MEM_STRESS_LIMIT_CPU}" "${MEM_STRESS_REQUEST_MEMORY}" "${MEM_STRESS_LIMIT_MEMORY}")"
  cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: device-avail-mem-stress
  namespace: ${NAMESPACE}
spec:
  ttlSecondsAfterFinished: 60
  template:
    spec:
      restartPolicy: Never
      nodeSelector:
        kubernetes.io/hostname: ${TARGET_NODE}
${priority_block}
      containers:
      - name: stress
        image: ${MEM_IMAGE}
        command: ["stress"]
        args: ["--vm", "${workers}", "--vm-bytes", "${vm_bytes}", "--vm-keep"]
${resource_block}
EOF
}

run_phase() {
  local phase_name="$1"
  local cpu_load_percent="$2"
  local memory_size_percent="$3"
  local duration_seconds="$4"
  local cpu_workers="${5:-0}"
  local mem_workers="${6:-0}"
  local mem_bytes="${7:-0}"

  echo "[INFO] phase=${phase_name} duration=${duration_seconds}s cpu=${cpu_load_percent} mem=${memory_size_percent}"
  delete_stress_jobs
  write_phase_state "${phase_name}" "${cpu_load_percent}" "${memory_size_percent}" "${duration_seconds}"

  if [[ "${cpu_workers}" != "0" ]]; then
    apply_cpu_job "${cpu_workers}"
  fi
  if [[ "${mem_workers}" != "0" ]]; then
    apply_mem_job "${mem_workers}" "${mem_bytes}"
  fi

  sleep "${duration_seconds}"
}

echo "[INFO] RUN_ID=${RUN_ID}"
echo "[INFO] OUT_DIR=${OUT_DIR}"
echo "[INFO] TARGET_NODE=${TARGET_NODE}"
echo "[INFO] NAMESPACE=${NAMESPACE}"
echo "[INFO] EXPERIMENT_PROFILE=${EXPERIMENT_PROFILE}"

if [[ "${EXPERIMENT_PROFILE}" == "cpu_smoke" ]]; then
  run_phase "BASELINE" "0" "0" "${BASELINE_SECONDS:-30}"
  run_phase "CPU-M" "65" "0" "${CPU_M_SECONDS:-60}" "${CPU_M_WORKERS:-4}"
  run_phase "RECOVERY-1" "0" "0" "${RECOVERY_1_SECONDS:-30}"
elif [[ "${EXPERIMENT_PROFILE}" == "mem_smoke" ]]; then
  run_phase "BASELINE" "0" "0" "${BASELINE_SECONDS:-30}"
  run_phase "MEM-M" "0" "60" "${MEM_M_SECONDS:-60}" "0" "${MEM_M_WORKERS:-1}" "${MEM_M_BYTES:-6G}"
  run_phase "RECOVERY-1" "0" "0" "${RECOVERY_1_SECONDS:-30}"
elif [[ "${EXPERIMENT_PROFILE}" == "mix_smoke" ]]; then
  run_phase "BASELINE" "0" "0" "${BASELINE_SECONDS:-30}"
  run_phase "MIX-H" "70" "65" "${MIX_H_SECONDS:-60}" "${MIX_H_CPU_WORKERS:-4}" "${MIX_H_MEM_WORKERS:-1}" "${MIX_H_MEM_BYTES:-7G}"
  run_phase "RECOVERY-1" "0" "0" "${RECOVERY_1_SECONDS:-30}"
elif [[ "${EXPERIMENT_PROFILE}" == "phase1_quick_validation" ]]; then
  run_phase "BASELINE" "0" "0" "${BASELINE_SECONDS:-1200}"
  run_phase "CPU-M" "65" "0" "${CPU_M_SECONDS:-1800}" "${CPU_M_WORKERS:-4}"
  run_phase "RECOVERY-1" "0" "0" "${RECOVERY_1_SECONDS:-600}"
  run_phase "MEM-M" "0" "60" "${MEM_M_SECONDS:-1800}" "0" "${MEM_M_WORKERS:-1}" "${MEM_M_BYTES:-6G}"
  run_phase "RECOVERY-2" "0" "0" "${RECOVERY_2_SECONDS:-600}"
  run_phase "MIX-M" "65" "60" "${MIX_M_SECONDS:-1800}" "${MIX_M_CPU_WORKERS:-4}" "${MIX_M_MEM_WORKERS:-1}" "${MIX_M_MEM_BYTES:-6G}"
  run_phase "FINAL-RECOVERY" "0" "0" "${FINAL_RECOVERY_SECONDS:-1200}"
elif [[ "${EXPERIMENT_PROFILE}" == "r1_pod_memory_limit_validation" ]]; then
  run_phase "BASELINE" "0" "0" "${BASELINE_SECONDS:-600}"
  run_phase "MEM-contained" "0" "55" "${MEM_CONTAINED_SECONDS:-1200}" "0" "${MEM_CONTAINED_WORKERS:-1}" "${MEM_CONTAINED_BYTES:-6G}"
  run_phase "RECOVERY-1" "0" "0" "${RECOVERY_1_SECONDS:-600}"
  run_phase "MEM-boundary" "0" "65" "${MEM_BOUNDARY_SECONDS:-1200}" "0" "${MEM_BOUNDARY_WORKERS:-1}" "${MEM_BOUNDARY_BYTES:-7G}"
  run_phase "FINAL-RECOVERY" "0" "0" "${FINAL_RECOVERY_SECONDS:-600}"
else
  run_phase "BASELINE" "0" "0" "${BASELINE_SECONDS:-1800}"
  run_phase "CPU-M" "65" "0" "${CPU_M_SECONDS:-3600}" "${CPU_M_WORKERS:-4}"
  run_phase "RECOVERY-1" "0" "0" "${RECOVERY_1_SECONDS:-1800}"
  run_phase "MEM-M" "0" "60" "${MEM_M_SECONDS:-3600}" "0" "${MEM_M_WORKERS:-1}" "${MEM_M_BYTES:-6G}"
  run_phase "RECOVERY-2" "0" "0" "${RECOVERY_2_SECONDS:-1800}"
  run_phase "MIX-H" "70" "65" "${MIX_H_SECONDS:-5400}" "${MIX_H_CPU_WORKERS:-4}" "${MIX_H_MEM_WORKERS:-1}" "${MIX_H_MEM_BYTES:-7G}"
  run_phase "FINAL-RECOVERY" "0" "0" "${FINAL_RECOVERY_SECONDS:-3600}"
fi

delete_stress_jobs
write_phase_state "COMPLETE" "0" "0" "0"
echo "[INFO] completed"
