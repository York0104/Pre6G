#!/usr/bin/env bash
set -e

TARGET_NODE="${1:-icclz3}"

echo "==> target node: ${TARGET_NODE}"
echo "==> recreating one-shot Job: vm-aggregator-once"

kubectl -n monitoring delete job vm-aggregator-once --ignore-not-found >/dev/null 2>&1 || true

cat <<YAML | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: vm-aggregator-once
  namespace: monitoring
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: aggregator
          image: python:3.12-slim
          command: ["python", "-u", "/app/vm_aggregator.py"]
          env:
            - name: VM_URL
              value: "http://vm-victoria-metrics-single-server.monitoring.svc:8428"
            - name: NETDATA_URL
              value: "http://netdata.netdata.svc:19999"
            - name: NETDATA_CHILD_URL
              value: "http://netdata.netdata.svc:19999"
            - name: NETDATA_PARENT_BASE_URL
              value: "http://netdata.netdata.svc:19999"
            - name: NODE
              value: "${TARGET_NODE}"
            - name: NAMESPACE
              value: "intent-lab"
            - name: RATE_WINDOW
              value: "10s"
            - name: SMOOTH_WINDOW
              value: "30s"
            - name: MODE
              value: "fast"
            - name: DEBUG_OUTPUT
              value: "1"
          volumeMounts:
            - name: script
              mountPath: /app
      volumes:
        - name: script
          configMap:
            name: vm-aggregator-script
            defaultMode: 0755
YAML

echo "==> waiting pod name ..."
while true; do
  POD_NAME="$(kubectl -n monitoring get pod -l job-name=vm-aggregator-once -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [ -n "${POD_NAME}" ]; then
    break
  fi
  sleep 0.2
done

echo "==> pod: ${POD_NAME}"
echo "==> waiting pod phase ..."
while true; do
  POD_PHASE="$(kubectl -n monitoring get pod "${POD_NAME}" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  if [ "${POD_PHASE}" = "Running" ] || [ "${POD_PHASE}" = "Succeeded" ] || [ "${POD_PHASE}" = "Failed" ]; then
    break
  fi
  sleep 0.2
done

echo "==> pod phase: ${POD_PHASE}"
echo "==> following logs ..."
kubectl -n monitoring logs -f "${POD_NAME}"
