#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="${SCRIPT_DIR}"
ROOT_DIR="$(cd "${BASE_DIR}/../../.." && pwd)"
NAMESPACE="${NAMESPACE:-intent-lab}"
FOCUS_DEPLOY="${FOCUS_DEPLOY:-yolo26n-task3-focus}"
BG_DEPLOY="${BG_DEPLOY:-yolo26n-task3-bg}"

TASK1_DURATION="${TASK1_DURATION:-1800}"
TASK1_EXPECTED_PODS="${TASK1_EXPECTED_PODS:-6}"
TASK1_FOCUS_REPLICAS="${TASK1_FOCUS_REPLICAS:-1}"
TASK1_BG_REPLICAS="${TASK1_BG_REPLICAS:-5}"
TASK1_MEAS_CONCURRENCY="${TASK1_MEAS_CONCURRENCY:-12}"
TASK1_MEAS_INTERVAL="${TASK1_MEAS_INTERVAL:-1.0}"
TASK1_TIMEOUT_SEC="${TASK1_TIMEOUT_SEC:-30}"
TASK1_REPEAT="${TASK1_REPEAT:-10}"

TASK2_DURATION="${TASK2_DURATION:-1800}"
TASK2_TIMEOUT_SEC="${TASK2_TIMEOUT_SEC:-30}"
TASK2_REPEAT="${TASK2_REPEAT:-10}"

TASK3_FAULT_HOLD_SECONDS="${TASK3_FAULT_HOLD_SECONDS:-1800}"
TASK3_TIMEOUT_SEC="${TASK3_TIMEOUT_SEC:-30}"
TASK3_REPEAT="${TASK3_REPEAT:-10}"
TASK3_FIXED_FAN_PCT="${TASK3_FIXED_FAN_PCT:-5}"

TASK4_NORMAL_HOLD_SECONDS="${TASK4_NORMAL_HOLD_SECONDS:-900}"
TASK4_FAULT_HOLD_SECONDS="${TASK4_FAULT_HOLD_SECONDS:-900}"
TASK4_RECOVERY_STABLE_SECONDS="${TASK4_RECOVERY_STABLE_SECONDS:-60}"
TASK4_RECOVERY_MAX_SECONDS="${TASK4_RECOVERY_MAX_SECONDS:-900}"
TASK4_FIXED_FAN_PCT="${TASK4_FIXED_FAN_PCT:-5}"
TASK4_BG_SIZE="${TASK4_BG_SIZE:-512}"
TASK4_BG_DUTY="${TASK4_BG_DUTY:-1.0}"
TASK4_BG_PERIOD_MS="${TASK4_BG_PERIOD_MS:-100}"
TASK4_REPEAT="${TASK4_REPEAT:-10}"
TASK4_TIMEOUT_SEC="${TASK4_TIMEOUT_SEC:-30}"

TASK_GAP_SECONDS="${TASK_GAP_SECONDS:-300}"
CC_PASSWORD="${CC_PASSWORD:-}"

STOP_REQUESTED=0
CURRENT_CHILD_PID=""

log() {
  printf '[RUN4TASK] %s\n' "$*"
}

require_env() {
  if [[ -z "${CC_PASSWORD}" ]]; then
    echo "missing CC_PASSWORD"
    echo "example:"
    echo "  CC_PASSWORD='your_password' bash experiments/experiments_yolo/run4task.sh"
    exit 1
  fi
}

cooldown() {
  local seconds="$1"
  if [[ "${seconds}" -le 0 ]]; then
    return 0
  fi

  log "Cooldown ${seconds}s before next task"
  while [[ "${seconds}" -gt 0 ]]; do
    if [[ "${STOP_REQUESTED}" -eq 1 ]]; then
      return 0
    fi
    if [[ "${seconds}" -ge 60 ]]; then
      log "Cooldown remaining: ${seconds}s"
      sleep 60
      seconds=$((seconds - 60))
    else
      log "Cooldown remaining: ${seconds}s"
      sleep "${seconds}"
      seconds=0
    fi
  done
}

forward_stop() {
  STOP_REQUESTED=1
  log "Stop requested"
  if [[ -n "${CURRENT_CHILD_PID}" ]]; then
    kill -INT "${CURRENT_CHILD_PID}" >/dev/null 2>&1 || true
  fi
}

trap forward_stop INT TERM

run_foreground_task() {
  local label="$1"
  shift

  log "START ${label}"
  "$@" &
  CURRENT_CHILD_PID=$!
  set +e
  wait "${CURRENT_CHILD_PID}"
  local rc=$?
  set -e
  CURRENT_CHILD_PID=""

  if [[ "${STOP_REQUESTED}" -eq 1 ]]; then
    log "STOP ${label} due to user interrupt"
    return 130
  fi

  if [[ "${rc}" -ne 0 ]]; then
    log "FAIL ${label} rc=${rc}"
    return "${rc}"
  fi

  log "END ${label}"
  return 0
}

prepare_task1_layout() {
  log "Prepare Task 1 layout: focus=${TASK1_FOCUS_REPLICAS}, bg=${TASK1_BG_REPLICAS}"
  kubectl -n "${NAMESPACE}" scale "deploy/${FOCUS_DEPLOY}" --replicas="${TASK1_FOCUS_REPLICAS}"
  kubectl -n "${NAMESPACE}" scale "deploy/${BG_DEPLOY}" --replicas="${TASK1_BG_REPLICAS}"
  kubectl -n "${NAMESPACE}" rollout status "deploy/${FOCUS_DEPLOY}" --timeout=180s
  kubectl -n "${NAMESPACE}" rollout status "deploy/${BG_DEPLOY}" --timeout=180s
}

task1() {
  EXPECTED_PODS="${TASK1_EXPECTED_PODS}" \
  DURATION="${TASK1_DURATION}" \
  MEAS_CONCURRENCY="${TASK1_MEAS_CONCURRENCY}" \
  MEAS_INTERVAL="${TASK1_MEAS_INTERVAL}" \
  TIMEOUT_SEC="${TASK1_TIMEOUT_SEC}" \
  REPEAT="${TASK1_REPEAT}" \
  bash "${BASE_DIR}/saturation_multi_pod/run_task3_service_load_with_metrics.sh"
}

task2() {
  DURATION="${TASK2_DURATION}" \
  TIMEOUT_SEC="${TASK2_TIMEOUT_SEC}" \
  REPEAT="${TASK2_REPEAT}" \
  bash "${BASE_DIR}/single_pod_serial/run_single_pod_serial_with_metrics.sh"
}

task3() {
  CC_PASSWORD="${CC_PASSWORD}" \
  FAULT_HOLD_SECONDS="${TASK3_FAULT_HOLD_SECONDS}" \
  TIMEOUT_SEC="${TASK3_TIMEOUT_SEC}" \
  REPEAT="${TASK3_REPEAT}" \
  FIXED_FAN_PCT="${TASK3_FIXED_FAN_PCT}" \
  bash "${BASE_DIR}/single_pod_serial_fault_fan/run_single_pod_serial_fault_fan.sh"
}

task4_once() {
  CC_PASSWORD="${CC_PASSWORD}" \
  CYCLES=1 \
  NORMAL_HOLD_SECONDS="${TASK4_NORMAL_HOLD_SECONDS}" \
  FAULT_HOLD_SECONDS="${TASK4_FAULT_HOLD_SECONDS}" \
  RECOVERY_STABLE_SECONDS="${TASK4_RECOVERY_STABLE_SECONDS}" \
  RECOVERY_MAX_SECONDS="${TASK4_RECOVERY_MAX_SECONDS}" \
  FIXED_FAN_PCT="${TASK4_FIXED_FAN_PCT}" \
  BG_SIZE="${TASK4_BG_SIZE}" \
  BG_DUTY="${TASK4_BG_DUTY}" \
  BG_PERIOD_MS="${TASK4_BG_PERIOD_MS}" \
  REPEAT="${TASK4_REPEAT}" \
  TIMEOUT_SEC="${TASK4_TIMEOUT_SEC}" \
  bash "${BASE_DIR}/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh"
}

main() {
  require_env
  cd "${ROOT_DIR}"

  log "Task 1: multi-pod saturation, 30 minutes"
  prepare_task1_layout
  run_foreground_task "task1" task1
  [[ "${STOP_REQUESTED}" -eq 1 ]] && exit 130

  cooldown "${TASK_GAP_SECONDS}"
  [[ "${STOP_REQUESTED}" -eq 1 ]] && exit 130

  log "Task 2: single pod serial normal fan, 30 minutes"
  run_foreground_task "task2" task2
  [[ "${STOP_REQUESTED}" -eq 1 ]] && exit 130

  cooldown "${TASK_GAP_SECONDS}"
  [[ "${STOP_REQUESTED}" -eq 1 ]] && exit 130

  log "Task 3: single pod serial fixed low fan, 30 minutes"
  run_foreground_task "task3" task3
  [[ "${STOP_REQUESTED}" -eq 1 ]] && exit 130

  cooldown "${TASK_GAP_SECONDS}"
  [[ "${STOP_REQUESTED}" -eq 1 ]] && exit 130

  log "Task 4: background-load fan cycle loop, press Ctrl+C to stop"
  local loop_idx=1
  while [[ "${STOP_REQUESTED}" -eq 0 ]]; do
    log "Task 4 loop iteration ${loop_idx}"
    run_foreground_task "task4_loop_${loop_idx}" task4_once
    if [[ "${STOP_REQUESTED}" -eq 1 ]]; then
      break
    fi
    loop_idx=$((loop_idx + 1))
  done

  log "run4task finished"
}

main "$@"
