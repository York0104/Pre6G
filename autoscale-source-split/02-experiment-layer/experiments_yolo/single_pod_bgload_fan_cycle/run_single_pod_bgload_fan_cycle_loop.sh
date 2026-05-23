#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/iccls2/AutoScale"
BASE_DIR="${ROOT_DIR}/experiments/experiments_yolo"

CC_PASSWORD="${CC_PASSWORD:-}"
LOOP_GAP_SECONDS="${LOOP_GAP_SECONDS:-0}"

STOP_REQUESTED=0
CURRENT_CHILD_PID=""

log() {
  printf '[BGLOAD_LOOP] %s\n' "$*"
}

require_env() {
  if [[ -z "${CC_PASSWORD}" ]]; then
    echo "missing CC_PASSWORD"
    echo "example:"
    echo "  CC_PASSWORD='your_password' bash experiments/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle_loop.sh"
    exit 1
  fi
}

forward_stop() {
  STOP_REQUESTED=1
  log "Stop requested"
  if [[ -n "${CURRENT_CHILD_PID}" ]]; then
    kill -INT "${CURRENT_CHILD_PID}" >/dev/null 2>&1 || true
  fi
}

trap forward_stop INT TERM

cooldown() {
  local seconds="$1"
  if [[ "${seconds}" -le 0 ]]; then
    return 0
  fi

  log "Cooldown ${seconds}s before next single-cycle run"
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

run_once() {
  CC_PASSWORD="${CC_PASSWORD}" \
  CYCLES=1 \
  bash "${BASE_DIR}/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh"
}

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

main() {
  require_env
  cd "${ROOT_DIR}"

  local loop_idx=1
  log "Single-cycle loop mode: press Ctrl+C to stop"
  while [[ "${STOP_REQUESTED}" -eq 0 ]]; do
    log "Loop iteration ${loop_idx}"
    run_foreground_task "single_cycle_${loop_idx}" run_once
    if [[ "${STOP_REQUESTED}" -eq 1 ]]; then
      break
    fi
    loop_idx=$((loop_idx + 1))
    cooldown "${LOOP_GAP_SECONDS}"
  done

  log "Loop finished"
}

main "$@"
