#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITORING_ENV_FILE="${MONITORING_ENV_FILE:-$SCRIPT_DIR/monitoring-runtime.host.env}"

if [[ -f "$MONITORING_ENV_FILE" ]]; then
  set -a
  . "$MONITORING_ENV_FILE"
  set +a
fi

TARGET_NODE="${1:-${TARGET_NODE:-icclz3}}"
MONITORING_NS="${MONITORING_NS:-monitoring}"
QUERY_NS="${QUERY_NS:-intent-lab}"
MODE="${MODE:-fast}"
RATE_WINDOW="${RATE_WINDOW:-10s}"
SMOOTH_WINDOW="${SMOOTH_WINDOW:-30s}"
DEBUG_OUTPUT="${DEBUG_OUTPUT:-1}"
KEEP_JOB="${KEEP_JOB:-0}"
JOB_PREFIX="${JOB_PREFIX:-vm-aggregator-once}"
VM_URL="${VM_URL:-http://140.113.179.9:31888}"
NETDATA_URL="${NETDATA_URL:-http://140.113.179.9:32163}"
NETDATA_CHILD_URL="${NETDATA_CHILD_URL:-$NETDATA_URL}"
NETDATA_PARENT_BASE_URL="${NETDATA_PARENT_BASE_URL:-$NETDATA_URL}"
SCRIPT_PATH="${SCRIPT_PATH:-$SCRIPT_DIR/vm_aggregator.py}"
SCRIPT_CONFIGMAP="${SCRIPT_CONFIGMAP:-vm-aggregator-script}"
PYTHON_IMAGE="${PYTHON_IMAGE:-python:3.12-slim}"

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "[ERROR] vm_aggregator.py not found: $SCRIPT_PATH" >&2
  exit 1
fi

sanitize_name() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g'
}

NODE_SLUG="$(sanitize_name "$TARGET_NODE")"
JOB_NAME="${JOB_PREFIX}-${NODE_SLUG}-$(date +%s)"

cleanup() {
  if [[ "$KEEP_JOB" != "1" ]]; then
    kubectl -n "$MONITORING_NS" delete job "$JOB_NAME" --ignore-not-found >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "==> target node: ${TARGET_NODE}"
echo "==> monitoring namespace: ${MONITORING_NS}"
echo "==> query namespace: ${QUERY_NS}"
if [[ -f "$MONITORING_ENV_FILE" ]]; then
  echo "==> env file: ${MONITORING_ENV_FILE}"
fi

VM_POD="${VM_POD:-vm-victoria-metrics-single-server-0}"
VM_READY="$(kubectl -n "$MONITORING_NS" get pod "$VM_POD" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || true)"
VM_PHASE="$(kubectl -n "$MONITORING_NS" get pod "$VM_POD" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
if [[ "$VM_READY" != "true" ]]; then
  echo "[ERROR] VictoriaMetrics pod is not Ready: ${VM_POD} (phase=${VM_PHASE:-unknown})" >&2
  echo "[ERROR] Check with: kubectl -n ${MONITORING_NS} get pod ${VM_POD} -o wide" >&2
  exit 1
fi

echo "==> syncing ConfigMap: ${SCRIPT_CONFIGMAP}"

kubectl -n "$MONITORING_NS" create configmap "$SCRIPT_CONFIGMAP" \
  --from-file=vm_aggregator.py="$SCRIPT_PATH" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "==> creating one-shot Job: ${JOB_NAME}"
cat <<YAML | kubectl apply -f - >/dev/null
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${MONITORING_NS}
spec:
  ttlSecondsAfterFinished: 300
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: aggregator
          image: ${PYTHON_IMAGE}
          command: ["python", "-u", "/app/vm_aggregator.py"]
          env:
            - name: VM_URL
              value: "${VM_URL}"
            - name: NETDATA_URL
              value: "${NETDATA_URL}"
            - name: NETDATA_CHILD_URL
              value: "${NETDATA_CHILD_URL}"
            - name: NETDATA_PARENT_BASE_URL
              value: "${NETDATA_PARENT_BASE_URL}"
            - name: NODE
              value: "${TARGET_NODE}"
            - name: NAMESPACE
              value: "${QUERY_NS}"
            - name: RATE_WINDOW
              value: "${RATE_WINDOW}"
            - name: SMOOTH_WINDOW
              value: "${SMOOTH_WINDOW}"
            - name: MODE
              value: "${MODE}"
            - name: DEBUG_OUTPUT
              value: "${DEBUG_OUTPUT}"
          volumeMounts:
            - name: script
              mountPath: /app
      volumes:
        - name: script
          configMap:
            name: ${SCRIPT_CONFIGMAP}
            defaultMode: 0755
YAML

echo "==> waiting for pod ..."
POD_NAME=""
for _ in $(seq 1 150); do
  POD_NAME="$(kubectl -n "$MONITORING_NS" get pod -l job-name="$JOB_NAME" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -n "$POD_NAME" ]]; then
    break
  fi
  sleep 0.2
done

if [[ -z "$POD_NAME" ]]; then
  echo "[ERROR] pod for job ${JOB_NAME} was not created in time" >&2
  exit 1
fi

echo "==> pod: ${POD_NAME}"
echo "==> waiting for completion ..."
if ! kubectl -n "$MONITORING_NS" wait --for=condition=complete --timeout=180s job/"$JOB_NAME" >/dev/null 2>&1; then
  echo "==> job did not reach Complete within timeout; showing pod status and logs" >&2
  kubectl -n "$MONITORING_NS" get pod "$POD_NAME" -o wide >&2 || true
  kubectl -n "$MONITORING_NS" logs "$POD_NAME" >&2 || true
  exit 1
fi

echo "==> output"
kubectl -n "$MONITORING_NS" logs "$POD_NAME"

if [[ "$KEEP_JOB" == "1" ]]; then
  trap - EXIT
  echo "==> keeping Job for inspection: ${JOB_NAME}"
fi
