#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

NAMESPACE="${NAMESPACE:-intent-lab}"
APP="${APP:-yolo26n}"
EXP="${EXP:-task3-saturation}"
GPU_NODE_NAME="${GPU_NODE_NAME:?missing GPU_NODE_NAME, e.g. icclz1}"
NODE_SSH_ALIAS="${NODE_SSH_ALIAS:-${GPU_NODE_NAME}-gpu}"
NODE_SSH="${NODE_SSH:-${NODE_SSH_ALIAS}}"
STACK_TEMPLATE="${STACK_TEMPLATE:-${SCRIPT_DIR}/yolo26_task3_saturation.yaml}"
STACK_RENDERED="${STACK_RENDERED:-/tmp/yolo26_task3_saturation_${GPU_NODE_NAME}.yaml}"
EXPECTED_PODS="${EXPECTED_PODS:-4}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-300}"
CLEANUP_ON_EXIT="${CLEANUP_ON_EXIT:-0}"

log_info() {
  echo "[INFO] $*"
}

log_error() {
  echo "[ERROR] $*" >&2
}

cleanup_stack() {
  kubectl delete -f "${STACK_RENDERED}" --ignore-not-found >/dev/null 2>&1 || true
}

if [ "${CLEANUP_ON_EXIT}" = "1" ]; then
  trap cleanup_stack EXIT
fi

if [ ! -f "${STACK_TEMPLATE}" ]; then
  log_error "missing stack template: ${STACK_TEMPLATE}"
  exit 1
fi

log_info "Checking target node ${GPU_NODE_NAME}..."
kubectl get node "${GPU_NODE_NAME}" -o wide

log_info "Rendering stack for node ${GPU_NODE_NAME}..."
GPU_NODE_NAME="${GPU_NODE_NAME}" python3 - "${STACK_TEMPLATE}" "${STACK_RENDERED}" <<'PY'
import os
import sys
from pathlib import Path

template = Path(sys.argv[1])
rendered = Path(sys.argv[2])
node_name = os.environ["GPU_NODE_NAME"]

text = template.read_text(encoding="utf-8")
text = text.replace("kubernetes.io/hostname: icclz1", f"kubernetes.io/hostname: {node_name}")
rendered.write_text(text, encoding="utf-8")
print(rendered)
PY

log_info "Applying saturation stack..."
kubectl apply -f "${STACK_RENDERED}"

log_info "Waiting for deployments rollout..."
kubectl -n "${NAMESPACE}" rollout status deploy/yolo26n-task3-focus --timeout="${WAIT_TIMEOUT_SECONDS}s"
kubectl -n "${NAMESPACE}" rollout status deploy/yolo26n-task3-bg --timeout="${WAIT_TIMEOUT_SECONDS}s"

log_info "Waiting for ${EXPECTED_PODS} running pods..."
deadline=$(( $(date +%s) + WAIT_TIMEOUT_SECONDS ))
while true; do
  running_count="$(
    kubectl -n "${NAMESPACE}" get pods \
      -l app="${APP}",exp="${EXP}" \
      -o jsonpath='{range .items[*]}{.status.phase}{"\n"}{end}' \
      | grep -c '^Running$' || true
  )"
  if [ "${running_count}" -eq "${EXPECTED_PODS}" ]; then
    break
  fi
  if [ "$(date +%s)" -ge "${deadline}" ]; then
    log_error "Timed out waiting for ${EXPECTED_PODS} running pods on ${GPU_NODE_NAME}"
    kubectl -n "${NAMESPACE}" get pods -l app="${APP}",exp="${EXP}" -o wide || true
    exit 2
  fi
  sleep 2
done

log_info "Pods are ready on ${GPU_NODE_NAME}:"
kubectl -n "${NAMESPACE}" get pods -l app="${APP}",exp="${EXP}" -o wide

log_info "Starting GPU-bound service load measurement..."
NODE_NAME="${GPU_NODE_NAME}" \
NODE_SSH="${NODE_SSH}" \
NODE_SSH_ALIAS="${NODE_SSH_ALIAS}" \
NAMESPACE="${NAMESPACE}" \
APP="${APP}" \
EXP="${EXP}" \
EXPECTED_PODS="${EXPECTED_PODS}" \
bash "${SCRIPT_DIR}/run_task3_service_load_with_metrics.sh"
