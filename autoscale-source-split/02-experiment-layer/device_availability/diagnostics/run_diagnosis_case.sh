#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

CASE_ID="${1:?case id required}"
RUN_ID="${2:-${CASE_ID}_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${ROOT_DIR}/results/${RUN_ID}}"
ITERATIONS="${ITERATIONS:-180}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-5}"
NAMESPACE="${NAMESPACE:-intent-lab}"
TARGET_HOST="${TARGET_HOST:-100.105.48.97}"

mkdir -p "${OUT_DIR}"

cleanup() {
  jobs -pr | xargs -r kill 2>/dev/null || true
  kubectl -n "${NAMESPACE}" delete job device-avail-cpu-stress --ignore-not-found=true >/dev/null 2>&1 || true
}
trap cleanup EXIT

run_case_d1() {
  bash "${SCRIPT_DIR}/run_observer_probe_loop.sh" "http://${TARGET_HOST}:18080/healthz" "${OUT_DIR}/observer_healthz.csv" "observer_healthz" &
  ITERATIONS="${ITERATIONS}" INTERVAL_SECONDS="${INTERVAL_SECONDS}" NAMESPACE="${NAMESPACE}" \
    bash "${SCRIPT_DIR}/run_localhost_probe_via_kubectl.sh" "/healthz" "${OUT_DIR}/local_healthz.csv" "local_healthz" &
}

run_case_d2() {
  bash "${SCRIPT_DIR}/run_observer_probe_loop.sh" "http://${TARGET_HOST}:18080/compute-check" "${OUT_DIR}/observer_compute.csv" "observer_compute" &
  ITERATIONS="${ITERATIONS}" INTERVAL_SECONDS="${INTERVAL_SECONDS}" NAMESPACE="${NAMESPACE}" \
    bash "${SCRIPT_DIR}/run_localhost_probe_via_kubectl.sh" "/compute-check" "${OUT_DIR}/local_compute.csv" "local_compute" &
}

run_case_d3() {
  bash "${SCRIPT_DIR}/run_observer_probe_loop.sh" "http://${TARGET_HOST}:18080/healthz" "${OUT_DIR}/observer_healthz.csv" "observer_healthz" &
  (sleep 1; bash "${SCRIPT_DIR}/run_observer_probe_loop.sh" "http://${TARGET_HOST}:18080/compute-check" "${OUT_DIR}/observer_compute.csv" "observer_compute") &
  ITERATIONS="${ITERATIONS}" INTERVAL_SECONDS="${INTERVAL_SECONDS}" NAMESPACE="${NAMESPACE}" \
    bash "${SCRIPT_DIR}/run_localhost_probe_via_kubectl.sh" "/healthz" "${OUT_DIR}/local_healthz.csv" "local_healthz" &
  (sleep 1; ITERATIONS="${ITERATIONS}" INTERVAL_SECONDS="${INTERVAL_SECONDS}" NAMESPACE="${NAMESPACE}" \
    bash "${SCRIPT_DIR}/run_localhost_probe_via_kubectl.sh" "/compute-check" "${OUT_DIR}/local_compute.csv" "local_compute") &
}

run_case_d4() {
  run_case_d3
  kubectl -n "${NAMESPACE}" apply -f "${ROOT_DIR}/manifests/cpu-stress-job.yaml" >/dev/null
}

kubectl -n "${NAMESPACE}" get ds node-sentinel -o wide > "${OUT_DIR}/daemonset_before.txt"
kubectl -n "${NAMESPACE}" get pods -l app=node-sentinel -o wide > "${OUT_DIR}/pods_before.txt"
kubectl -n "${NAMESPACE}" logs ds/node-sentinel --tail=200 > "${OUT_DIR}/sentinel_logs_before.jsonl" || true

case "${CASE_ID}" in
  D1) run_case_d1 ;;
  D2) run_case_d2 ;;
  D3) run_case_d3 ;;
  D4) run_case_d4 ;;
  *) echo "Unknown case: ${CASE_ID}" >&2; exit 1 ;;
esac

wait

kubectl -n "${NAMESPACE}" get ds node-sentinel -o wide > "${OUT_DIR}/daemonset_after.txt"
kubectl -n "${NAMESPACE}" get pods -l app=node-sentinel -o wide > "${OUT_DIR}/pods_after.txt"
kubectl -n "${NAMESPACE}" get events --sort-by=.metadata.creationTimestamp > "${OUT_DIR}/events_after.txt" || true
kubectl -n "${NAMESPACE}" logs ds/node-sentinel --tail=500 > "${OUT_DIR}/sentinel_logs_after.jsonl" || true

trap - EXIT
