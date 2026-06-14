#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="${SCRIPT_DIR}/run_remote_benchmark_with_metrics.sh"
PLOTTER="${SCRIPT_DIR}/plot_remote_benchmark_suite.py"
MASTER_PYTHON_BIN="${MASTER_PYTHON_BIN:-${SCRIPT_DIR}/../../../iccl/bin/python}"
MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/pre6g-matplotlib}"

SUITE_ID="${SUITE_ID:-remote_suite_$(date +%Y%m%d_%H%M%S)}"
RESULT_ROOT="${RESULT_ROOT:-${SCRIPT_DIR}/results}"
SUITE_DIR="${RESULT_ROOT}/${SUITE_ID}"
TASK_ORDER="${TASK_ORDER:-cpu_bound ram_bound vram_bound}"
DEFAULT_WARMUP_SECONDS="${DEFAULT_WARMUP_SECONDS:-300}"
DEFAULT_STEADY_SECONDS="${DEFAULT_STEADY_SECONDS:-2700}"
DEFAULT_COOLDOWN_SECONDS="${DEFAULT_COOLDOWN_SECONDS:-900}"
FIXED_COOLDOWN_SECONDS="${FIXED_COOLDOWN_SECONDS:-$DEFAULT_COOLDOWN_SECONDS}"
COOLDOWN_TIMEOUT_SECONDS="${COOLDOWN_TIMEOUT_SECONDS:-900}"
COOLDOWN_TIMEOUT_POLICY="${COOLDOWN_TIMEOUT_POLICY:-warn-and-continue}"
BASELINE_CPU_PERCENT_MAX="${BASELINE_CPU_PERCENT_MAX:-15}"
BASELINE_GPU_PERCENT_MAX="${BASELINE_GPU_PERCENT_MAX:-5}"
BASELINE_VRAM_MARGIN_PERCENT="${BASELINE_VRAM_MARGIN_PERCENT:-1.0}"
BASELINE_RAM_MARGIN_PERCENT="${BASELINE_RAM_MARGIN_PERCENT:-2.5}"
COOLDOWN_POLL_INTERVAL_SECONDS="${COOLDOWN_POLL_INTERVAL_SECONDS:-5}"
WORKER_SSH="${WORKER_SSH:-mirc516@100.90.127.1}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/mirc516/Pre6g}"
SSH_OPTS="${SSH_OPTS:- -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10}"

mkdir -p "${SUITE_DIR}"
mkdir -p "${MPLCONFIGDIR}"

log_info() {
  echo "[INFO] $*"
}

log_error() {
  echo "[ERROR] $*" >&2
}

write_suite_summary() {
  local suite_status="$1"
  local suite_failure="$2"
  local plotting_status="$3"
  local plotting_error="$4"
  python3 - "${SUITE_ID}" "${SUITE_DIR}" "${suite_status}" "${suite_failure}" "${plotting_status}" "${plotting_error}" <<'PY'
import csv
import json
import sys
from pathlib import Path

suite_id, suite_dir, suite_status, suite_failure, plotting_status, plotting_error = sys.argv[1:]
suite_path = Path(suite_dir)
manifest_path = suite_path / "suite_manifest.csv"
summary_path = suite_path / "suite_summary.json"

rows = []
if manifest_path.exists():
    with manifest_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

summary = {
    "suite_id": suite_id,
    "suite_dir": str(suite_path),
    "status": suite_status,
    "failure_category": suite_failure,
    "task_order": [row["task"] for row in rows],
    "tasks": rows,
    "artifacts": {
        "manifest": str(manifest_path),
        "suite_plot": str(suite_path / "suite_resource_utilization.png"),
        "suite_plot_summary": str(suite_path / "suite_plot_summary.json"),
    },
    "plotting": {
        "status": plotting_status,
        "error": plotting_error or "",
    },
}
summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, ensure_ascii=False))
PY
}

generate_suite_compatibility_artifacts() {
  mkdir -p "${SUITE_DIR}/plots"
  if [ -f "${SUITE_DIR}/suite_resource_utilization.png" ]; then
    cp -f "${SUITE_DIR}/suite_resource_utilization.png" "${SUITE_DIR}/plots/suite_resource_utilization.png"
  fi

  "${MASTER_PYTHON_BIN}" - "${SUITE_DIR}" <<'PY' > "${SUITE_DIR}/summary.txt"
import json
import sys
from pathlib import Path

suite_dir = Path(sys.argv[1])
summary_path = suite_dir / "suite_summary.json"
manifest_path = suite_dir / "suite_manifest.csv"
summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}

print(f"suite_id: {summary.get('suite_id', suite_dir.name)}")
print(f"status: {summary.get('status', '')}")
print(f"failure_category: {summary.get('failure_category', '')}")
print(f"task_order: {' '.join(summary.get('task_order', []))}")
print(f"manifest: {manifest_path}")
print(f"suite_plot: {suite_dir / 'suite_resource_utilization.png'}")
for task in summary.get("tasks", []):
    print(
        "task="
        f"{task.get('task','')} "
        f"run_id={task.get('run_id','')} "
        f"status={task.get('status','')} "
        f"summary_success={task.get('summary_success','')} "
        f"combined_monitor_path={task.get('combined_monitor_path','')}"
    )
PY
}

capture_remote_metrics_json() {
  ssh ${SSH_OPTS} "${WORKER_SSH}" "${REMOTE_ROOT}/iccl/bin/python" - <<'PY'
import json
import subprocess
import time

import psutil


def run_nvidia_smi():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        used_mb, total_mb, gpu_util = [int(part.strip()) for part in result.stdout.strip().split(",")]
        vram_percent = round((used_mb / total_mb) * 100, 2) if total_mb else None
        return used_mb, total_mb, gpu_util, vram_percent
    except Exception:
        return None, None, None, None


cpu_percent = psutil.cpu_percent(interval=1.0)
vm = psutil.virtual_memory()
used_mb, total_mb, gpu_util, vram_percent = run_nvidia_smi()
print(
    json.dumps(
        {
            "timestamp": time.time(),
            "cpu_percent": round(cpu_percent, 2),
            "ram_used_percent": round(vm.percent, 2),
            "gpu_util_percent": gpu_util,
            "vram_used_percent": vram_percent,
            "vram_used_mb": used_mb,
            "vram_total_mb": total_mb,
        }
    )
)
PY
}

is_cooldown_ready() {
  local metrics_json="$1"
  local baseline_json="$2"
  local previous_kind="$3"
  python3 - "${metrics_json}" "${baseline_json}" "${previous_kind}" "${BASELINE_CPU_PERCENT_MAX}" "${BASELINE_GPU_PERCENT_MAX}" "${BASELINE_VRAM_MARGIN_PERCENT}" "${BASELINE_RAM_MARGIN_PERCENT}" <<'PY'
import json
import sys

metrics = json.loads(sys.argv[1])
baseline = json.loads(sys.argv[2])
previous_kind = sys.argv[3]
cpu_limit = float(sys.argv[4])
gpu_limit = float(sys.argv[5])
vram_margin = float(sys.argv[6])
ram_margin = float(sys.argv[7])

cpu = metrics.get("cpu_percent") or 0.0
ram = metrics.get("ram_used_percent") or 0.0
gpu = metrics.get("gpu_util_percent") or 0.0
vram = metrics.get("vram_used_percent") or 0.0

baseline_ram = baseline.get("ram_used_percent") or 0.0
baseline_vram = baseline.get("vram_used_percent") or 0.0

if previous_kind == "cpu_bound":
    ready = cpu <= cpu_limit and gpu <= gpu_limit and vram <= max(2.0, baseline_vram + vram_margin)
elif previous_kind == "ram_bound":
    ready = cpu <= cpu_limit and ram <= baseline_ram + ram_margin and gpu <= gpu_limit
elif previous_kind == "vram_bound":
    ready = cpu <= 20.0 and gpu <= gpu_limit and vram <= max(2.0, baseline_vram + vram_margin)
else:
    ready = cpu <= cpu_limit and gpu <= gpu_limit

print("true" if ready else "false")
PY
}

log_info "SUITE_ID=${SUITE_ID}"
log_info "SUITE_DIR=${SUITE_DIR}"
log_info "TASK_ORDER=${TASK_ORDER}"
log_info "FIXED_COOLDOWN_SECONDS=${FIXED_COOLDOWN_SECONDS}"
log_info "COOLDOWN_TIMEOUT_SECONDS=${COOLDOWN_TIMEOUT_SECONDS}"
log_info "COOLDOWN_TIMEOUT_POLICY=${COOLDOWN_TIMEOUT_POLICY}"

{
  echo "suite_id,task_index,task,run_id,run_dir,status,failure_category,remote_exit_code,summary_success,task_start_epoch,task_end_epoch,remote_end_epoch,cooldown_ready,cooldown_extra_wait_sec,cooldown_policy_outcome,master_verdict_path,worker_summary_path,worker_monitor_path,combined_monitor_path"
} > "${SUITE_DIR}/suite_manifest.csv"

set +e
BASELINE_JSON="$(capture_remote_metrics_json 2>"${SUITE_DIR}/baseline_capture.err")"
BASELINE_EXIT=$?
set -e
if [ "${BASELINE_EXIT}" -ne 0 ] || [ -z "${BASELINE_JSON}" ]; then
  write_suite_summary "failed" "preflight_failed" "skipped" "baseline capture failed" > "${SUITE_DIR}/suite_summary.log"
  log_error "Baseline capture failed. See ${SUITE_DIR}/baseline_capture.err"
  exit 1
fi

printf '%s\n' "${BASELINE_JSON}" > "${SUITE_DIR}/baseline.json"

SUITE_STATUS="success"
SUITE_FAILURE_CATEGORY=""
PLOTTING_STATUS="success"
PLOTTING_ERROR=""
TASK_INDEX=0

for TASK_NAME in ${TASK_ORDER}; do
  TASK_INDEX=$((TASK_INDEX + 1))
  RUN_ID="${TASK_NAME}_$(date +%Y%m%d_%H%M%S)"
  RUN_DIR="${RESULT_ROOT}/${RUN_ID}"

  log_info "Starting task ${TASK_INDEX}: ${TASK_NAME} (RUN_ID=${RUN_ID})"

  set +e
  TASK="${TASK_NAME}" RUN_ID="${RUN_ID}" RESULT_ROOT="${RESULT_ROOT}" FIXED_COOLDOWN_SECONDS="${FIXED_COOLDOWN_SECONDS}" bash "${RUNNER}" > "${SUITE_DIR}/${RUN_ID}.console.log" 2>&1
  RUN_EXIT=$?
  set -e

  VERDICT_PATH="${RUN_DIR}/master_verdict.json"
  if [ ! -f "${VERDICT_PATH}" ]; then
    SUITE_STATUS="failed"
    SUITE_FAILURE_CATEGORY="summary_missing"
    break
  fi

  VERDICT_JSON="$(cat "${VERDICT_PATH}")"
  TASK_STATUS="$(python3 -c 'import sys,json; print("success" if json.load(sys.stdin)["overall_success"] else "failed")' <<<"${VERDICT_JSON}")"
  FAILURE_CATEGORY="$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("failure_category",""))' <<<"${VERDICT_JSON}")"
  REMOTE_EXIT_CODE="$(python3 -c 'import sys,json; print(json.load(sys.stdin)["stages"]["remote_wrapper"]["exit_code"])' <<<"${VERDICT_JSON}")"
  SUMMARY_SUCCESS="$(python3 -c 'import sys,json; print(str(json.load(sys.stdin)["stages"]["summary"]["success"]).lower())' <<<"${VERDICT_JSON}")"
  TASK_START_EPOCH="$(python3 -c 'import sys,json; v=json.load(sys.stdin)["timing"]["start_epoch"]; print("" if v is None else v)' <<<"${VERDICT_JSON}")"
  TASK_END_EPOCH="$(python3 -c 'import sys,json; v=json.load(sys.stdin)["timing"]["end_epoch"]; print("" if v is None else v)' <<<"${VERDICT_JSON}")"
  REMOTE_END_EPOCH="$(python3 -c 'import sys,json; v=json.load(sys.stdin)["timing"]["remote_end_epoch"]; print("" if v is None else v)' <<<"${VERDICT_JSON}")"
  WORKER_SUMMARY_PATH="$(python3 -c 'import sys,json; print(json.load(sys.stdin)["artifacts"]["local_summary_path"])' <<<"${VERDICT_JSON}")"
  WORKER_MONITOR_PATH="$(python3 -c 'import sys,json; print(json.load(sys.stdin)["artifacts"]["local_monitor_path"])' <<<"${VERDICT_JSON}")"
  COMBINED_MONITOR_PATH="$(python3 -c 'import sys,json; print(json.load(sys.stdin)["artifacts"]["combined_monitor_csv"])' <<<"${VERDICT_JSON}")"

  COOLDOWN_READY="false"
  COOLDOWN_EXTRA_WAIT_SEC="0"
  COOLDOWN_POLICY_OUTCOME="not_applicable"
  if [ "${TASK_STATUS}" = "success" ] && [ "${TASK_INDEX}" -lt "$(wc -w <<<"${TASK_ORDER}")" ]; then
    COOLDOWN_WAIT_STARTED="$(date +%s)"
    while true; do
      CURRENT_JSON="$(capture_remote_metrics_json)"
      READY="$(is_cooldown_ready "${CURRENT_JSON}" "${BASELINE_JSON}" "${TASK_NAME}")"
      if [ "${READY}" = "true" ]; then
        COOLDOWN_READY="true"
        break
      fi

      NOW_EPOCH="$(date +%s)"
      ELAPSED_WAIT="$((NOW_EPOCH - COOLDOWN_WAIT_STARTED))"
      if [ "${ELAPSED_WAIT}" -ge "${COOLDOWN_TIMEOUT_SECONDS}" ]; then
        COOLDOWN_READY="false"
        COOLDOWN_EXTRA_WAIT_SEC="${ELAPSED_WAIT}"
        if [ "${COOLDOWN_TIMEOUT_POLICY}" = "fail" ]; then
          COOLDOWN_POLICY_OUTCOME="fail"
          TASK_STATUS="failed"
          FAILURE_CATEGORY="cooldown_timeout"
          SUITE_STATUS="failed"
          SUITE_FAILURE_CATEGORY="cooldown_timeout"
        else
          COOLDOWN_POLICY_OUTCOME="warn-and-continue"
          log_error "Cooldown timeout for ${TASK_NAME}, continue by policy"
        fi
        break
      fi

      sleep "${COOLDOWN_POLL_INTERVAL_SECONDS}"
    done
    if [ "${COOLDOWN_READY}" = "true" ]; then
      NOW_EPOCH="$(date +%s)"
      COOLDOWN_EXTRA_WAIT_SEC="$((NOW_EPOCH - COOLDOWN_WAIT_STARTED))"
      COOLDOWN_POLICY_OUTCOME="ready"
    fi
  fi

  echo "${SUITE_ID},${TASK_INDEX},${TASK_NAME},${RUN_ID},${RUN_DIR},${TASK_STATUS},${FAILURE_CATEGORY},${REMOTE_EXIT_CODE},${SUMMARY_SUCCESS},${TASK_START_EPOCH},${TASK_END_EPOCH},${REMOTE_END_EPOCH},${COOLDOWN_READY},${COOLDOWN_EXTRA_WAIT_SEC},${COOLDOWN_POLICY_OUTCOME},${VERDICT_PATH},${WORKER_SUMMARY_PATH},${WORKER_MONITOR_PATH},${COMBINED_MONITOR_PATH}" >> "${SUITE_DIR}/suite_manifest.csv"

  if [ "${RUN_EXIT}" -ne 0 ] || [ "${TASK_STATUS}" != "success" ]; then
    SUITE_STATUS="failed"
    SUITE_FAILURE_CATEGORY="${FAILURE_CATEGORY:-remote_wrapper_failed}"
    break
  fi
done

set +e
MPLCONFIGDIR="${MPLCONFIGDIR}" "${MASTER_PYTHON_BIN}" "${PLOTTER}" --suite-dir "${SUITE_DIR}" > "${SUITE_DIR}/suite_plot.log" 2>&1
PLOT_EXIT=$?
set -e
if [ "${PLOT_EXIT}" -ne 0 ]; then
  PLOTTING_STATUS="failed"
  PLOTTING_ERROR="plotting_failed"
fi

write_suite_summary "${SUITE_STATUS}" "${SUITE_FAILURE_CATEGORY}" "${PLOTTING_STATUS}" "${PLOTTING_ERROR}" > "${SUITE_DIR}/suite_summary.log"
generate_suite_compatibility_artifacts

if [ "${SUITE_STATUS}" = "success" ]; then
  log_info "Suite completed successfully. Summary: ${SUITE_DIR}/suite_summary.json"
  exit 0
fi

log_error "Suite failed with category: ${SUITE_FAILURE_CATEGORY}"
exit 1
