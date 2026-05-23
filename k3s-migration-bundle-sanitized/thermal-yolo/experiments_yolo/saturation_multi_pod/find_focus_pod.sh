#!/usr/bin/env bash
set -euo pipefail

NS=intent-lab

FOCUS_POD=$(kubectl -n "$NS" get pod \
  -l app=yolo26n,exp=task3-saturation,role=focus \
  -o jsonpath='{.items[0].metadata.name}')

FOCUS_IP=$(kubectl -n "$NS" get pod "$FOCUS_POD" \
  -o jsonpath='{.status.podIP}')

NODE_NAME=$(kubectl -n "$NS" get pod "$FOCUS_POD" \
  -o jsonpath='{.spec.nodeName}')

echo "FOCUS_POD=$FOCUS_POD"
echo "FOCUS_IP=$FOCUS_IP"
echo "NODE_NAME=$NODE_NAME"
echo "FOCUS_URL=http://${FOCUS_IP}:18080/infer"
