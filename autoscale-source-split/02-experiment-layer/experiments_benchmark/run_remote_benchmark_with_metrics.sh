#!/usr/bin/env bash
set -euo pipefail

TASK="${TASK:?missing TASK: cpu_bound|ram_bound|vram_bound}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPLIT_ROOT="$(cd "${BASE_DIR}/.." && pwd)"
MONITORING_DIR="${SPLIT_ROOT}/01-monitoring-layer"
VM_AGG_COLLECTOR="${BASE_DIR}/thermal_analysis/collect_vm_aggregator_csv.py"
VM_AGGREGATOR="${MONITORING_DIR}/vm_aggregator.py"
VM_AGG_TRAINING="${SPLIT_ROOT}/02-experiment-layer/experiments_yolo/common/extract_vmagg_training_features.py"
MASTER_PYTHON_BIN="${MASTER_PYTHON_BIN:-${SPLIT_ROOT}/../iccl/bin/python}"

WORKER_SSH="${WORKER_SSH:-mirc516@100.90.127.1}"
WORKER_NODE_NAME="${WORKER_NODE_NAME:-ICCL-S3-251230}"
K8S_NODE_NAME="${K8S_NODE_NAME:-}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/mirc516/Pre6g}"
SSH_OPTS="${SSH_OPTS:- -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10}"
MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/pre6g-matplotlib}"

VM_URL="${VM_URL:-http://140.113.179.9:31888}"
NETDATA_URL="${NETDATA_URL:-http://140.113.179.9:32163}"
NETDATA_CHILD_URL="${NETDATA_CHILD_URL:-$NETDATA_URL}"
NETDATA_PARENT_BASE_URL="${NETDATA_PARENT_BASE_URL:-$NETDATA_URL}"

DURATION="${DURATION:-}"
DEFAULT_WARMUP_SECONDS="${DEFAULT_WARMUP_SECONDS:-300}"
DEFAULT_STEADY_SECONDS="${DEFAULT_STEADY_SECONDS:-2700}"
DEFAULT_COOLDOWN_SECONDS="${DEFAULT_COOLDOWN_SECONDS:-900}"
FIXED_COOLDOWN_SECONDS="${FIXED_COOLDOWN_SECONDS:-$DEFAULT_COOLDOWN_SECONDS}"
RAM_LOAD_ESTIMATE_SECONDS="${RAM_LOAD_ESTIMATE_SECONDS:-$((DEFAULT_WARMUP_SECONDS + DEFAULT_STEADY_SECONDS))}"
VM_AGG_INTERVAL="${VM_AGG_INTERVAL:-1.0}"
MONITOR_HEADROOM_SECONDS="${MONITOR_HEADROOM_SECONDS:-120}"
ENABLE_KUBECTL_TOP="${ENABLE_KUBECTL_TOP:-1}"
ENABLE_REMOTE_NVIDIA_SMI="${ENABLE_REMOTE_NVIDIA_SMI:-1}"

RESULT_ROOT="${RESULT_ROOT:-${SCRIPT_DIR}/results}"
RUN_ID="${RUN_ID:-${TASK}_$(date +%Y%m%d_%H%M%S)}"
RUN_DIR="${RESULT_ROOT}/${RUN_ID}"

mkdir -p "${RESULT_ROOT}" "${RUN_DIR}" "${RUN_DIR}/worker_logs"
mkdir -p "${MPLCONFIGDIR}"

GPU_PID=""
TOP_PID=""
VM_AGG_PID=""
PREFLIGHT_EXIT=""
REMOTE_EXIT=""
ARTIFACT_PULL_EXIT=""
PLOTTING_EXIT=""
SUMMARY_STATUS="pending"
SUMMARY_SUCCESS="false"
SUMMARY_ERROR=""
FAILURE_CATEGORY=""
PREFLIGHT_OK="false"
ARTIFACT_PULL_OK="false"
PLOTTING_OK="false"
REMOTE_WRAPPER_OK="false"

START_EPOCH=""
START_ISO=""
REMOTE_END_EPOCH=""
REMOTE_END_ISO=""
END_EPOCH=""
END_ISO=""

REMOTE_SUMMARY_PATH=""
REMOTE_MONITOR_PATH=""
SUMMARY_BASENAME=""
MONITOR_BASENAME=""
SUMMARY_LOCAL_PATH=""
MONITOR_LOCAL_PATH=""
RUN_PHASE_KIND=""
MONITOR_BASE_SECONDS=""
VM_AGG_SECONDS=""
MONITOR_WINDOW_SOURCE=""

log_info() {
  echo "[INFO] $*"
}

log_error() {
  echo "[ERROR] $*" >&2
}

append_env_assignments() {
  local result="$1"
  shift
  local name quoted
  for name in "$@"; do
    if [ -n "${!name+x}" ]; then
      printf -v quoted "%q" "${!name}"
      result+=" ${name}=${quoted}"
    fi
  done
  printf '%s' "${result}"
}

cleanup() {
  kill "${GPU_PID:-}" "${TOP_PID:-}" "${VM_AGG_PID:-}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

resolve_k8s_node_name() {
  if [ -n "${K8S_NODE_NAME}" ]; then
    return 0
  fi

  local remote_host_candidates
  remote_host_candidates="$(
    ssh ${SSH_OPTS} "${WORKER_SSH}" 'hostname; hostname -s; hostname -f 2>/dev/null || true' 2>/dev/null \
      | awk 'NF' \
      | awk '!seen[$0]++'
  )"

  K8S_NODE_NAME="$(
    NODES="$(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{\"\n\"}{end}' 2>/dev/null || true)" \
    CANDIDATES="${remote_host_candidates}" \
    WORKER_NAME="${WORKER_NODE_NAME}" \
    python3 - <<'PY'
import os

node_names = [line.strip() for line in os.environ.get("NODES", "").splitlines() if line.strip()]
candidates = [line.strip() for line in os.environ.get("CANDIDATES", "").splitlines() if line.strip()]
worker_name = os.environ.get("WORKER_NAME", "").strip()
if worker_name:
    candidates.extend([worker_name, worker_name.lower(), worker_name.replace("_", "-").lower()])

def variants(text):
    t = text.strip()
    lower = t.lower()
    return {t, lower, lower.replace("_", "-")}

best_name = ""
best_score = -1
for node_name in node_names:
    node_variants = variants(node_name)
    for candidate in candidates:
        candidate_variants = variants(candidate)
        score = -1
        if node_variants & candidate_variants:
            score = 100
        else:
            cl = candidate.lower().replace("_", "-")
            nl = node_name.lower()
            if cl in nl or nl in cl:
                score = 80
        if score > best_score:
            best_name = node_name
            best_score = score

if best_name:
    print(best_name)
PY
  )"

  if [ -z "${K8S_NODE_NAME}" ]; then
    K8S_NODE_NAME="${WORKER_NODE_NAME}"
  fi
}

capture_cluster_state() {
  local phase="$1"
  {
    echo "# node"
    kubectl get node "${K8S_NODE_NAME}" -o wide || true
    echo
    echo "# pods_on_worker"
    kubectl get pods -A --field-selector "spec.nodeName=${K8S_NODE_NAME}" -o wide || true
  } > "${RUN_DIR}/deploy_${phase}.txt" 2>&1 || true

  kubectl get pods -A --field-selector "spec.nodeName=${K8S_NODE_NAME}" -o wide \
    > "${RUN_DIR}/pods_${phase}.txt" 2>&1 || true

  kubectl get events -A --sort-by=.lastTimestamp | tail -n 50 \
    > "${RUN_DIR}/events_${phase}.txt" 2>&1 || true
}

generate_compatibility_artifacts() {
  mkdir -p "${RUN_DIR}/plots"

  if [ -f "${RUN_DIR}/kubectl_top_node_1s.log" ]; then
    cp -f "${RUN_DIR}/kubectl_top_node_1s.log" "${RUN_DIR}/kubectl_top_1s.log"
  fi
  if [ -f "${RUN_DIR}/worker_nvidia_smi_1s.csv" ]; then
    cp -f "${RUN_DIR}/worker_nvidia_smi_1s.csv" "${RUN_DIR}/nvidia_smi_gpu_1s.csv"
  fi
  if [ -f "${RUN_DIR}/worker_nvidia_smi_1s.err" ]; then
    cp -f "${RUN_DIR}/worker_nvidia_smi_1s.err" "${RUN_DIR}/nvidia_smi_gpu_1s.err"
  fi
  if [ -f "${RUN_DIR}/remote_wrapper.log" ]; then
    cp -f "${RUN_DIR}/remote_wrapper.log" "${RUN_DIR}/measurement.log"
  fi
  if [ -f "${RUN_DIR}/resource_utilization.png" ]; then
    cp -f "${RUN_DIR}/resource_utilization.png" "${RUN_DIR}/plots/resource_utilization.png"
    cp -f "${RUN_DIR}/resource_utilization.png" "${RUN_DIR}/plots/${TASK}_resource_utilization.png"
  fi

  if [ -f "${RUN_DIR}/combined_monitor.csv" ]; then
    "${MASTER_PYTHON_BIN}" - "${RUN_DIR}" "${TASK}" "${RUN_ID}" <<'PY' > "${RUN_DIR}/measurement_transform.log" 2>&1
import csv
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
task = sys.argv[2]
run_id = sys.argv[3]
src = run_dir / "combined_monitor.csv"
dst = run_dir / "measurement_raw.csv"

with src.open("r", newline="", encoding="utf-8") as in_handle, dst.open("w", newline="", encoding="utf-8") as out_handle:
    reader = csv.DictReader(in_handle)
    fieldnames = [
        "run_id",
        "task",
        "timestamp",
        "elapsed_s",
        "cpu_percent",
        "ram_used_percent",
        "gpu_util_percent",
        "vram_used_percent",
    ]
    writer = csv.DictWriter(out_handle, fieldnames=fieldnames)
    writer.writeheader()
    for row in reader:
        writer.writerow(
            {
                "run_id": run_id,
                "task": task,
                "timestamp": row.get("timestamp", ""),
                "elapsed_s": row.get("elapsed_s", ""),
                "cpu_percent": row.get("cpu_percent", ""),
                "ram_used_percent": row.get("ram_used_percent", ""),
                "gpu_util_percent": row.get("gpu_util_percent", ""),
                "vram_used_percent": row.get("vram_used_percent", ""),
            }
        )
PY
  fi

  if [ -f "${RUN_DIR}/vm_aggregator_timeseries.csv" ] && [ -f "${VM_AGG_TRAINING}" ]; then
    "${MASTER_PYTHON_BIN}" "${VM_AGG_TRAINING}" \
      --input "${RUN_DIR}/vm_aggregator_timeseries.csv" \
      > "${RUN_DIR}/vm_aggregator_training_features.log" 2>&1 || true
  fi

  "${MASTER_PYTHON_BIN}" - "${RUN_DIR}" <<'PY' > "${RUN_DIR}/summary.txt"
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
verdict_path = run_dir / "master_verdict.json"
plot_summary_path = run_dir / "plot_summary.json"
worker_logs_dir = run_dir / "worker_logs"

verdict = json.loads(verdict_path.read_text(encoding="utf-8")) if verdict_path.exists() else {}
plot_summary = json.loads(plot_summary_path.read_text(encoding="utf-8")) if plot_summary_path.exists() else {}

worker_summary = {}
for candidate in ("video_summary.json", "redis_summary.json", "qwen_summary.json"):
    path = worker_logs_dir / candidate
    if path.exists():
      worker_summary = json.loads(path.read_text(encoding="utf-8"))
      break

print(f"run_id: {verdict.get('run_id', run_dir.name)}")
print(f"task: {verdict.get('task', '')}")
print(f"overall_success: {verdict.get('overall_success')}")
print(f"failure_category: {verdict.get('failure_category', '')}")
timing = verdict.get("timing", {})
print(f"start_iso: {timing.get('start_iso', '')}")
print(f"remote_end_iso: {timing.get('remote_end_iso', '')}")
print(f"end_iso: {timing.get('end_iso', '')}")
print(f"worker_summary_success: {worker_summary.get('success', '')}")
print(f"worker_summary_task: {worker_summary.get('task', '')}")
print(f"worker_summary_bound_type: {worker_summary.get('bound_type', '')}")
print(f"worker_summary_duration_sec: {worker_summary.get('duration_sec', '')}")
print(f"plot_rows: {plot_summary.get('rows', '')}")
print(f"combined_monitor_csv: {run_dir / 'combined_monitor.csv'}")
print(f"measurement_raw_csv: {run_dir / 'measurement_raw.csv'}")
print(f"vm_aggregator_training_features_csv: {run_dir / 'vm_aggregator_training_features.csv'}")
PY
}

run_remote_task_preflight() {
  local task_name="$1"
  local input_path="${2:-}"
  local redis_host="${3:-127.0.0.1}"
  local redis_port="${4:-6379}"
  local model_name="${5:-qwen3:32b}"
  local pdf_path="${6:-}"
  local task_name_q remote_root_q input_path_q redis_host_q redis_port_q model_name_q pdf_path_q

  printf -v task_name_q "%q" "${task_name}"
  printf -v remote_root_q "%q" "${REMOTE_ROOT}"
  printf -v input_path_q "%q" "${input_path}"
  printf -v redis_host_q "%q" "${redis_host}"
  printf -v redis_port_q "%q" "${redis_port}"
  printf -v model_name_q "%q" "${model_name}"
  printf -v pdf_path_q "%q" "${pdf_path}"

  ssh ${SSH_OPTS} "${WORKER_SSH}" \
    "TASK_NAME=${task_name_q} REMOTE_ROOT=${remote_root_q} INPUT_PATH=${input_path_q} REDIS_HOST=${redis_host_q} REDIS_PORT=${redis_port_q} MODEL_NAME=${model_name_q} PDF_PATH=${pdf_path_q} bash -s" \
    <<'REMOTE'
set -euo pipefail

: "${TASK_NAME:?}"
: "${REMOTE_ROOT:?}"
: "${INPUT_PATH:=}"
: "${REDIS_HOST:=127.0.0.1}"
: "${REDIS_PORT:=6379}"
: "${MODEL_NAME:=qwen3:32b}"
: "${PDF_PATH:=}"
PYTHON_BIN="${REMOTE_ROOT}/iccl/bin/python"

cd "${REMOTE_ROOT}"

require_file() {
  local path="$1"
  test -f "$path" || {
    echo "missing file: $path" >&2
    exit 1
  }
}

require_python_imports() {
  local imports="$1"
  "${PYTHON_BIN}" - <<PY
${imports}
PY
}

case "${TASK_NAME}" in
  cpu_bound)
    command -v ffmpeg >/dev/null
    ENCODERS_OUTPUT="$(ffmpeg -hide_banner -encoders 2>/dev/null || true)"
    printf '%s\n' "${ENCODERS_OUTPUT}" | grep -q 'libx265'
    test -x "${PYTHON_BIN}"
    require_python_imports $'import ffmpeg\nimport psutil'
    if [ -z "${INPUT_PATH}" ]; then
      INPUT_PATH="${REMOTE_ROOT}/input_4k.mp4"
    fi
    require_file "${INPUT_PATH}"
    ;;
  ram_bound)
    command -v redis-cli >/dev/null
    redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping | grep -q 'PONG'
    test -x "${PYTHON_BIN}"
    require_python_imports $'import redis'
    ;;
  vram_bound)
    command -v curl >/dev/null
    command -v ollama >/dev/null
    command -v nvidia-smi >/dev/null
    TAGS_JSON="$(curl -fsS http://127.0.0.1:11434/api/tags)"
    TAGS_JSON="${TAGS_JSON}" "${PYTHON_BIN}" - "${MODEL_NAME}" <<'PY'
import json
import os
import sys

model_name = sys.argv[1]
payload = json.loads(os.environ["TAGS_JSON"])
models = payload.get("models", [])
names = [item.get("name") for item in models if isinstance(item, dict)]
sys.exit(0 if model_name in names else 1)
PY
    nvidia-smi >/dev/null
    test -x "${PYTHON_BIN}"
    require_python_imports $'import fitz\nfrom ollama import Client'
    if [ -z "${PDF_PATH}" ]; then
      PDF_PATH="${REMOTE_ROOT}/Attention Is All You Need.pdf"
    fi
    require_file "${PDF_PATH}"
    ;;
  *)
    echo "unknown task: ${TASK_NAME}" >&2
    exit 2
    ;;
esac
REMOTE
}

write_verdict() {
  SUMMARY_LOCAL_PATH="${RUN_DIR}/worker_logs/${SUMMARY_BASENAME}"
  MONITOR_LOCAL_PATH="${RUN_DIR}/worker_logs/${MONITOR_BASENAME}"

  python3 - "${RUN_ID}" "${TASK}" "${RUN_DIR}" "${PREFLIGHT_OK}" "${PREFLIGHT_EXIT}" "${REMOTE_WRAPPER_OK}" "${REMOTE_EXIT}" "${ARTIFACT_PULL_OK}" "${ARTIFACT_PULL_EXIT}" "${SUMMARY_STATUS}" "${SUMMARY_SUCCESS}" "${SUMMARY_ERROR}" "${PLOTTING_OK}" "${PLOTTING_EXIT}" "${FAILURE_CATEGORY}" "${REMOTE_SUMMARY_PATH}" "${REMOTE_MONITOR_PATH}" "${SUMMARY_LOCAL_PATH}" "${MONITOR_LOCAL_PATH}" "${START_EPOCH}" "${START_ISO}" "${REMOTE_END_EPOCH}" "${REMOTE_END_ISO}" "${END_EPOCH}" "${END_ISO}" "${FIXED_COOLDOWN_SECONDS}" "${RUN_PHASE_KIND}" "${MONITOR_WINDOW_SOURCE}" "${MONITOR_BASE_SECONDS}" "${VM_AGG_SECONDS}" <<'PY' \
    | tee "${RUN_DIR}/master_verdict.json"
import json
import sys
from pathlib import Path

(
    run_id,
    task,
    run_dir,
    preflight_ok,
    preflight_exit,
    remote_wrapper_ok,
    remote_exit,
    artifact_pull_ok,
    artifact_pull_exit,
    summary_status,
    summary_success,
    summary_error,
    plotting_ok,
    plotting_exit,
    failure_category,
    remote_summary_path,
    remote_monitor_path,
    local_summary_path,
    local_monitor_path,
    start_epoch,
    start_iso,
    remote_end_epoch,
    remote_end_iso,
    end_epoch,
    end_iso,
    fixed_cooldown_seconds,
    run_phase_kind,
    monitor_window_source,
    monitor_base_seconds,
    vm_agg_seconds,
) = sys.argv[1:]

summary_data = None
summary_error_detail = summary_error
summary_path = Path(local_summary_path)
monitor_path = Path(local_monitor_path)
if summary_path.exists():
    if summary_status == "summary_parse_failed":
        try:
            summary_path.read_text(encoding="utf-8")
        except Exception as exc:
            summary_error_detail = str(exc)
    elif summary_status == "success":
        try:
            summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:
            summary_error_detail = str(exc)
            summary_data = None

verdict = {
    "run_id": run_id,
    "task": task,
    "run_dir": run_dir,
    "overall_success": (
        preflight_ok == "true"
        and remote_wrapper_ok == "true"
        and artifact_pull_ok == "true"
        and summary_success == "true"
    ),
    "failure_category": failure_category or "",
    "stages": {
        "preflight": {
            "ok": preflight_ok == "true",
            "exit_code": int(preflight_exit) if preflight_exit else None,
        },
        "remote_wrapper": {
            "ok": remote_wrapper_ok == "true",
            "exit_code": int(remote_exit) if remote_exit else None,
        },
        "artifact_pull": {
            "ok": artifact_pull_ok == "true",
            "exit_code": int(artifact_pull_exit) if artifact_pull_exit else None,
        },
        "summary": {
            "status": summary_status,
            "success": summary_success == "true",
            "error": summary_error_detail,
        },
        "plotting": {
            "ok": plotting_ok == "true",
            "exit_code": int(plotting_exit) if plotting_exit else None,
        },
    },
    "timing": {
        "start_epoch": float(start_epoch) if start_epoch else None,
        "start_iso": start_iso or None,
        "remote_end_epoch": float(remote_end_epoch) if remote_end_epoch else None,
        "remote_end_iso": remote_end_iso or None,
        "end_epoch": float(end_epoch) if end_epoch else None,
        "end_iso": end_iso or None,
        "fixed_cooldown_seconds": float(fixed_cooldown_seconds),
        "phase_kind": run_phase_kind,
    },
    "monitor_window": {
        "source": monitor_window_source,
        "base_seconds": float(monitor_base_seconds) if monitor_base_seconds else None,
        "vm_agg_seconds": float(vm_agg_seconds) if vm_agg_seconds else None,
    },
    "artifacts": {
        "remote_summary_path": remote_summary_path,
        "remote_monitor_path": remote_monitor_path,
        "local_summary_path": str(summary_path),
        "local_monitor_path": str(monitor_path),
        "local_summary_exists": summary_path.exists(),
        "local_monitor_exists": monitor_path.exists(),
        "worker_logs_dir": str(Path(run_dir) / "worker_logs"),
        "combined_monitor_csv": str(Path(run_dir) / "combined_monitor.csv"),
        "plot_path": str(Path(run_dir) / "resource_utilization.png"),
    },
}
if summary_data is not None:
    verdict["summary_excerpt"] = {
        key: summary_data.get(key)
        for key in ("task", "bound_type", "success", "duration_sec", "start_time", "end_time")
    }
print(json.dumps(verdict, indent=2, ensure_ascii=False))
PY
}

case "${TASK}" in
  cpu_bound)
    RUN_PHASE_KIND="cpu_bound"
    REMOTE_RUN_CMD="export RUN_ID=$(printf %q "${RUN_ID}")"
    REMOTE_RUN_CMD="$(append_env_assignments "${REMOTE_RUN_CMD}" INPUT_PATH OUTPUT_PATH MONITOR_LOG SUMMARY_JSON CODEC PRESET CRF THREADS PARALLEL_JOBS TIMEOUT_SECONDS KEEP_OUTPUT)"
    if [ -n "${MIN_DURATION_SECONDS+x}" ]; then
      REMOTE_RUN_CMD="$(append_env_assignments "${REMOTE_RUN_CMD}" MIN_DURATION_SECONDS)"
      MONITOR_BASE_SECONDS="${MIN_DURATION_SECONDS}"
      MONITOR_WINDOW_SOURCE="min_duration_seconds"
    elif [ -n "${DURATION}" ]; then
      REMOTE_RUN_CMD+=" MIN_DURATION_SECONDS=$(printf %q "${DURATION}")"
      MONITOR_BASE_SECONDS="${DURATION}"
      MONITOR_WINDOW_SOURCE="duration_fallback"
    else
      DEFAULT_TASK_SECONDS="$((DEFAULT_WARMUP_SECONDS + DEFAULT_STEADY_SECONDS))"
      REMOTE_RUN_CMD+=" MIN_DURATION_SECONDS=$(printf %q "${DEFAULT_TASK_SECONDS}")"
      MONITOR_BASE_SECONDS="${DEFAULT_TASK_SECONDS}"
      MONITOR_WINDOW_SOURCE="master_default_profile"
    fi
    REMOTE_RUN_CMD+="; bash $(printf %q "${REMOTE_ROOT}/run_task_cpu.sh")"
    REMOTE_SUMMARY_PATH="${REMOTE_ROOT}/logs/master_runs/${RUN_ID}/video_summary.json"
    REMOTE_MONITOR_PATH="${REMOTE_ROOT}/logs/master_runs/${RUN_ID}/video_cpu.csv"
    SUMMARY_BASENAME="video_summary.json"
    MONITOR_BASENAME="video_cpu.csv"
    ;;
  ram_bound)
    RUN_PHASE_KIND="ram_bound"
    REMOTE_RUN_CMD="export RUN_ID=$(printf %q "${RUN_ID}")"
    REMOTE_RUN_CMD="$(append_env_assignments "${REMOTE_RUN_CMD}" LOG_ROOT HOST PORT DB TARGET_KEYS DATA_SIZE_KB BATCH_SIZE KEY_PREFIX STATS_LOG SUMMARY_JSON SAMPLE_INTERVAL STOP_ON_MEMORY_THRESHOLD_GB CLEANUP POST_CLEANUP_PURGE POST_CLEANUP_RESTART_REDIS)"
    if [ -n "${HOLD_SECONDS+x}" ]; then
      REMOTE_RUN_CMD="$(append_env_assignments "${REMOTE_RUN_CMD}" HOLD_SECONDS)"
      HOLD_BASE_SECONDS="${HOLD_SECONDS}"
      MONITOR_WINDOW_SOURCE="hold_seconds"
    elif [ -n "${DURATION}" ]; then
      REMOTE_RUN_CMD+=" HOLD_SECONDS=$(printf %q "${DURATION}")"
      HOLD_BASE_SECONDS="${DURATION}"
      MONITOR_WINDOW_SOURCE="duration_fallback"
    else
      REMOTE_RUN_CMD+=" HOLD_SECONDS=$(printf %q "${DEFAULT_STEADY_SECONDS}")"
      HOLD_BASE_SECONDS="${DEFAULT_STEADY_SECONDS}"
      MONITOR_WINDOW_SOURCE="master_default_profile"
    fi
    MONITOR_BASE_SECONDS="$((RAM_LOAD_ESTIMATE_SECONDS + HOLD_BASE_SECONDS))"
    REMOTE_RUN_CMD+="; bash $(printf %q "${REMOTE_ROOT}/run_task_ram.sh")"
    REMOTE_SUMMARY_PATH="${REMOTE_ROOT}/logs/master_runs/${RUN_ID}/redis_summary.json"
    REMOTE_MONITOR_PATH="${REMOTE_ROOT}/logs/master_runs/${RUN_ID}/redis_stats.csv"
    SUMMARY_BASENAME="redis_summary.json"
    MONITOR_BASENAME="redis_stats.csv"
    ;;
  vram_bound)
    RUN_PHASE_KIND="vram_bound"
    REMOTE_RUN_CMD="export RUN_ID=$(printf %q "${RUN_ID}")"
    REMOTE_RUN_CMD="$(append_env_assignments "${REMOTE_RUN_CMD}" LOG_ROOT PYTHON_BIN MODEL_NAME PDF_PATH GPU_LOG SUMMARY_JSON CONCURRENCY REPEAT MAX_CHARS NUM_CTX NUM_PREDICT KEEP_ALIVE)"
    if [ -n "${MIN_DURATION_SECONDS+x}" ]; then
      REMOTE_RUN_CMD="$(append_env_assignments "${REMOTE_RUN_CMD}" MIN_DURATION_SECONDS)"
      MONITOR_BASE_SECONDS="${MIN_DURATION_SECONDS}"
      MONITOR_WINDOW_SOURCE="min_duration_seconds"
    elif [ -n "${DURATION}" ]; then
      REMOTE_RUN_CMD+=" MIN_DURATION_SECONDS=$(printf %q "${DURATION}")"
      MONITOR_BASE_SECONDS="${DURATION}"
      MONITOR_WINDOW_SOURCE="duration_fallback"
    else
      DEFAULT_TASK_SECONDS="$((DEFAULT_WARMUP_SECONDS + DEFAULT_STEADY_SECONDS))"
      REMOTE_RUN_CMD+=" MIN_DURATION_SECONDS=$(printf %q "${DEFAULT_TASK_SECONDS}")"
      MONITOR_BASE_SECONDS="${DEFAULT_TASK_SECONDS}"
      MONITOR_WINDOW_SOURCE="master_default_profile"
    fi
    REMOTE_RUN_CMD+="; bash $(printf %q "${REMOTE_ROOT}/run_task_vram.sh")"
    REMOTE_SUMMARY_PATH="${REMOTE_ROOT}/logs/master_runs/${RUN_ID}/qwen_summary.json"
    REMOTE_MONITOR_PATH="${REMOTE_ROOT}/logs/master_runs/${RUN_ID}/qwen_gpu.csv"
    SUMMARY_BASENAME="qwen_summary.json"
    MONITOR_BASENAME="qwen_gpu.csv"
    ;;
  *)
    log_error "Unknown TASK=${TASK}"
    exit 2
    ;;
esac

VM_AGG_SECONDS="$((MONITOR_BASE_SECONDS + FIXED_COOLDOWN_SECONDS + MONITOR_HEADROOM_SECONDS))"

{
  echo "RUN_ID=${RUN_ID}"
  echo "RUN_DIR=${RUN_DIR}"
  echo "TASK=${TASK}"
  echo "WORKER_SSH=${WORKER_SSH}"
  echo "WORKER_NODE_NAME=${WORKER_NODE_NAME}"
  echo "REMOTE_ROOT=${REMOTE_ROOT}"
  echo "DURATION=${DURATION}"
  echo "MIN_DURATION_SECONDS=${MIN_DURATION_SECONDS:-}"
  echo "HOLD_SECONDS=${HOLD_SECONDS:-}"
  echo "DEFAULT_WARMUP_SECONDS=${DEFAULT_WARMUP_SECONDS}"
  echo "DEFAULT_STEADY_SECONDS=${DEFAULT_STEADY_SECONDS}"
  echo "DEFAULT_COOLDOWN_SECONDS=${DEFAULT_COOLDOWN_SECONDS}"
  echo "FIXED_COOLDOWN_SECONDS=${FIXED_COOLDOWN_SECONDS}"
  echo "RAM_LOAD_ESTIMATE_SECONDS=${RAM_LOAD_ESTIMATE_SECONDS}"
  echo "MONITOR_WINDOW_SOURCE=${MONITOR_WINDOW_SOURCE}"
  echo "MONITOR_BASE_SECONDS=${MONITOR_BASE_SECONDS}"
  echo "VM_AGG_SECONDS=${VM_AGG_SECONDS}"
  echo "VM_URL=${VM_URL}"
  echo "NETDATA_URL=${NETDATA_URL}"
  echo "NETDATA_CHILD_URL=${NETDATA_CHILD_URL}"
  echo "NETDATA_PARENT_BASE_URL=${NETDATA_PARENT_BASE_URL}"
} | tee "${RUN_DIR}/experiment_config.txt"

log_info "Task-aware preflight on worker..."
set +e
run_remote_task_preflight \
  "${TASK}" \
  "${INPUT_PATH:-${REMOTE_ROOT}/input_4k.mp4}" \
  "${HOST:-127.0.0.1}" \
  "${PORT:-6379}" \
  "${MODEL_NAME:-qwen3:32b}" \
  "${PDF_PATH:-${REMOTE_ROOT}/Attention Is All You Need.pdf}" \
  > "${RUN_DIR}/preflight.log" 2>&1
PREFLIGHT_EXIT=$?
set -e
if [ "${PREFLIGHT_EXIT}" -eq 0 ]; then
  PREFLIGHT_OK="true"
else
  FAILURE_CATEGORY="preflight_failed"
  log_error "Preflight failed. See ${RUN_DIR}/preflight.log"
  write_verdict
  exit 1
fi

resolve_k8s_node_name
echo "K8S_NODE_NAME=${K8S_NODE_NAME}" | tee -a "${RUN_DIR}/experiment_config.txt"
capture_cluster_state "before"

if [ "${ENABLE_REMOTE_NVIDIA_SMI}" = "1" ]; then
  log_info "Starting remote nvidia-smi monitor..."
  ssh ${SSH_OPTS} "${WORKER_SSH}" \
    "nvidia-smi --query-gpu=timestamp,index,name,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm,clocks.mem --format=csv -l 1" \
    > "${RUN_DIR}/worker_nvidia_smi_1s.csv" 2> "${RUN_DIR}/worker_nvidia_smi_1s.err" &
  GPU_PID=$!
fi

if [ "${ENABLE_KUBECTL_TOP}" = "1" ]; then
  log_info "Starting kubectl top node monitor..."
  (
    while true; do
      echo "timestamp,$(date -Is)"
      kubectl top node "${K8S_NODE_NAME}" --no-headers || true
      echo "----"
      sleep 1
    done
  ) > "${RUN_DIR}/kubectl_top_node_1s.log" 2>&1 &
  TOP_PID=$!
fi

START_EPOCH="$(date +%s)"
START_ISO="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "START_EPOCH=${START_EPOCH}" | tee "${RUN_DIR}/time_window.txt"
echo "START_ISO=${START_ISO}" | tee -a "${RUN_DIR}/time_window.txt"

log_info "Starting vm_aggregator collector..."
python3 "${VM_AGG_COLLECTOR}" \
  --aggregator "${VM_AGGREGATOR}" \
  --out "${RUN_DIR}/vm_aggregator_timeseries.csv" \
  --seconds "${VM_AGG_SECONDS}" \
  --interval "${VM_AGG_INTERVAL}" \
  --node "${K8S_NODE_NAME}" \
  --vm-url "${VM_URL}" \
  --netdata-url "${NETDATA_URL}" \
  --netdata-child-url "${NETDATA_CHILD_URL}" \
  --netdata-parent-base-url "${NETDATA_PARENT_BASE_URL}" \
  --mode fast \
  > "${RUN_DIR}/vm_aggregator_timeseries.log" 2>&1 &
VM_AGG_PID=$!

log_info "Running remote benchmark wrapper..."
set +e
ssh ${SSH_OPTS} "${WORKER_SSH}" "${REMOTE_RUN_CMD}" > "${RUN_DIR}/remote_wrapper.log" 2>&1
REMOTE_EXIT=$?
set -e
if [ "${REMOTE_EXIT}" -eq 0 ]; then
  REMOTE_WRAPPER_OK="true"
else
  FAILURE_CATEGORY="remote_wrapper_failed"
fi

REMOTE_END_EPOCH="$(date +%s)"
REMOTE_END_ISO="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "REMOTE_END_EPOCH=${REMOTE_END_EPOCH}" | tee -a "${RUN_DIR}/time_window.txt"
echo "REMOTE_END_ISO=${REMOTE_END_ISO}" | tee -a "${RUN_DIR}/time_window.txt"

if [ "${FIXED_COOLDOWN_SECONDS}" -gt 0 ]; then
  log_info "Fixed cooldown observation for ${FIXED_COOLDOWN_SECONDS}s..."
  sleep "${FIXED_COOLDOWN_SECONDS}"
fi

END_EPOCH="$(date +%s)"
END_ISO="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "END_EPOCH=${END_EPOCH}" | tee -a "${RUN_DIR}/time_window.txt"
echo "END_ISO=${END_ISO}" | tee -a "${RUN_DIR}/time_window.txt"

kill "${GPU_PID:-}" "${TOP_PID:-}" 2>/dev/null || true
kill "${VM_AGG_PID:-}" 2>/dev/null || true
wait "${VM_AGG_PID:-}" || true
sleep 2

capture_cluster_state "after"

log_info "Pulling worker logs back..."
set +e
rsync -e "ssh ${SSH_OPTS}" -av \
  "${WORKER_SSH}:${REMOTE_ROOT}/logs/master_runs/${RUN_ID}/" \
  "${RUN_DIR}/worker_logs/" \
  > "${RUN_DIR}/rsync_worker_logs.log" 2>&1
ARTIFACT_PULL_EXIT=$?
set -e
if [ "${ARTIFACT_PULL_EXIT}" -eq 0 ]; then
  ARTIFACT_PULL_OK="true"
else
  if [ -z "${FAILURE_CATEGORY}" ]; then
    FAILURE_CATEGORY="artifact_pull_failed"
  fi
fi

log_info "Exporting VictoriaMetrics query_range snapshots..."
python3 - "${VM_URL}" "${START_EPOCH}" "${END_EPOCH}" "${RUN_DIR}" "${K8S_NODE_NAME}" <<'PY'
import sys
import urllib.parse
import urllib.request
from pathlib import Path

vm_url = sys.argv[1].rstrip("/")
start = sys.argv[2]
end = sys.argv[3]
run_dir = Path(sys.argv[4])
node_name = sys.argv[5]

queries = {
    "node_cpu_util_percent": f'100 - avg by (instance) (rate(node_cpu_seconds_total{{instance=~".*{node_name}.*",mode="idle"}}[1m])) * 100',
    "node_mem_util_percent": f'(1 - node_memory_MemAvailable_bytes{{instance=~".*{node_name}.*"}} / node_memory_MemTotal_bytes{{instance=~".*{node_name}.*"}}) * 100',
    "node_load1": f'node_load1{{instance=~".*{node_name}.*"}}',
    "node_load5": f'node_load5{{instance=~".*{node_name}.*"}}',
    "node_load15": f'node_load15{{instance=~".*{node_name}.*"}}',
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

SUMMARY_LOCAL_PATH="${RUN_DIR}/worker_logs/${SUMMARY_BASENAME}"
MONITOR_LOCAL_PATH="${RUN_DIR}/worker_logs/${MONITOR_BASENAME}"

if [ ! -f "${SUMMARY_LOCAL_PATH}" ]; then
  SUMMARY_STATUS="summary_missing"
  SUMMARY_SUCCESS="false"
  SUMMARY_ERROR="summary file not found"
  if [ -z "${FAILURE_CATEGORY}" ]; then
    FAILURE_CATEGORY="summary_missing"
  fi
else
  set +e
  python3 - "${SUMMARY_LOCAL_PATH}" <<'PY' >/dev/null 2>"${RUN_DIR}/summary_parse.err"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
sys.exit(0 if data.get("success") is True else 2)
PY
  SUMMARY_PARSE_EXIT=$?
  set -e
  case "${SUMMARY_PARSE_EXIT}" in
    0)
      SUMMARY_STATUS="success"
      SUMMARY_SUCCESS="true"
      ;;
    2)
      SUMMARY_STATUS="summary_failed"
      SUMMARY_SUCCESS="false"
      SUMMARY_ERROR="summary success != true"
      if [ -z "${FAILURE_CATEGORY}" ]; then
        FAILURE_CATEGORY="remote_wrapper_failed"
      fi
      ;;
    *)
      SUMMARY_STATUS="summary_parse_failed"
      SUMMARY_SUCCESS="false"
      SUMMARY_ERROR="$(tr '\n' ' ' < "${RUN_DIR}/summary_parse.err" | sed 's/[[:space:]]\+/ /g' | sed 's/^ //; s/ $//')"
      if [ -z "${FAILURE_CATEGORY}" ]; then
        FAILURE_CATEGORY="summary_parse_failed"
      fi
      ;;
  esac
fi

if MPLCONFIGDIR="${MPLCONFIGDIR}" "${MASTER_PYTHON_BIN}" "${SCRIPT_DIR}/plot_remote_benchmark_run.py" --run-dir "${RUN_DIR}" > "${RUN_DIR}/plot_run.log" 2>&1; then
  PLOTTING_OK="true"
  PLOTTING_EXIT="0"
else
  PLOTTING_OK="false"
  PLOTTING_EXIT="$?"
  if [ -z "${FAILURE_CATEGORY}" ]; then
    FAILURE_CATEGORY="plotting_failed"
  fi
fi

write_verdict
generate_compatibility_artifacts

if [ "${PREFLIGHT_OK}" = "true" ] && [ "${REMOTE_WRAPPER_OK}" = "true" ] && [ "${ARTIFACT_PULL_OK}" = "true" ] && [ "${SUMMARY_SUCCESS}" = "true" ]; then
  log_info "Completed. Results in ${RUN_DIR}"
  exit 0
fi

log_error "Run failed with category: ${FAILURE_CATEGORY}"
exit 1
