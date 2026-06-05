#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_LAYER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPLIT_ROOT="$(cd "${EXPERIMENT_LAYER_DIR}/.." && pwd)"
PRE6G_ROOT="$(cd "${SPLIT_ROOT}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${PRE6G_ROOT}/iccl/bin/python}"

RUN_ID="${1:-single_yolo26_rate_sweep_$(date +%Y%m%d_%H%M%S)}"
OUTDIR="${OUTDIR:-${HOME}/exp_runs/${RUN_ID}}"

NS="${NS:-intent-lab}"
DEPLOY="${DEPLOY:-yolo26n-focus}"
WORKER_IP="${WORKER_IP:-140.113.179.6}"
PORT="${PORT:-18081}"
DURATION="${DURATION:-120}"
WARMUP_SECONDS="${WARMUP_SECONDS:-20}"
RATE_WARMUP_SECONDS="${RATE_WARMUP_SECONDS:-5}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-15}"

# Comma-separated request rates. The script converts each rate to interval=1/rps.
RATES_RPS="${RATES_RPS:-1,2,3,4,5,6,8,10,12,15,20}"

IMAGE_PATH="${TEST_IMAGE:-${EXPERIMENT_LAYER_DIR}/yolo26_workload/test_images/sanity_input.png}"
CLIENT="${CLIENT:-${EXPERIMENT_LAYER_DIR}/thermal_analysis/yolo26_latency_client_stable.py}"

mkdir -p "${OUTDIR}/raw" "${OUTDIR}/logs" "${OUTDIR}/k8s" "${OUTDIR}/summary"

echo "[INFO] RUN_ID=${RUN_ID}"
echo "[INFO] OUTDIR=${OUTDIR}"
echo "[INFO] namespace=${NS}"
echo "[INFO] single deployment=${DEPLOY}"
echo "[INFO] target=http://${WORKER_IP}:${PORT}/infer"
echo "[INFO] RATES_RPS=${RATES_RPS}"
echo "[INFO] DURATION=${DURATION}"

if [ ! -f "${IMAGE_PATH}" ]; then
  echo "[ERROR] TEST_IMAGE not found: ${IMAGE_PATH}"
  exit 1
fi

echo "[INFO] Scale YOLO deployments: keep ${DEPLOY}=1, disable bg pods"
kubectl -n "${NS}" scale deploy/yolo26n-bg-1 --replicas=0
kubectl -n "${NS}" scale deploy/yolo26n-bg-2 --replicas=0
kubectl -n "${NS}" scale "deploy/${DEPLOY}" --replicas=1
kubectl -n "${NS}" rollout status "deploy/${DEPLOY}"

echo "[INFO] Wait for background YOLO pods to disappear"
for role in bg-1 bg-2; do
  for _ in $(seq 1 60); do
    count="$(kubectl -n "${NS}" get pods -l "app=yolo26n,role=${role}" --no-headers 2>/dev/null | wc -l | xargs)"
    if [ "${count}" = "0" ]; then
      break
    fi
    sleep 1
  done
done

kubectl -n "${NS}" get deploy yolo26n-focus yolo26n-bg-1 yolo26n-bg-2 \
  -o custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas \
  | tee "${OUTDIR}/k8s/deployments_before_sweep.txt"
kubectl -n "${NS}" get pods -l app=yolo26n -o wide | tee "${OUTDIR}/k8s/pods_before_sweep.txt"

echo "[INFO] Health check"
curl -sS -o /dev/null \
  --connect-timeout 2 \
  --max-time 5 \
  -w "http_code=%{http_code} connect=%{time_connect} total=%{time_total}\n" \
  "http://${WORKER_IP}:${PORT}/healthz" \
  | tee "${OUTDIR}/logs/pre_healthz.txt"

echo "[INFO] Warmup ${WARMUP_SECONDS}s at 1 rps"
"${PYTHON_BIN}" "${CLIENT}" \
  --url "http://${WORKER_IP}:${PORT}/infer" \
  --image "${IMAGE_PATH}" \
  --seconds "${WARMUP_SECONDS}" \
  --interval 1 \
  --csv "${OUTDIR}/raw/warmup.csv" \
  > "${OUTDIR}/logs/warmup.log" 2>&1

SUMMARY_CSV="${OUTDIR}/summary/rate_sweep_summary.csv"
echo "rate_rps,achieved_rps,interval_sec,total,success,failures,success_rate_pct,status_codes,client_latency_ms_mean,client_latency_ms_p95,client_latency_ms_p99,client_latency_ms_max,server_latency_ms_mean,server_latency_ms_p95,server_latency_ms_p99,server_latency_ms_max" > "${SUMMARY_CSV}"

IFS=',' read -r -a RATE_LIST <<< "${RATES_RPS}"
for rate in "${RATE_LIST[@]}"; do
  rate="$(echo "${rate}" | xargs)"
  if [ -z "${rate}" ]; then
    continue
  fi

  interval="$(awk -v r="${rate}" 'BEGIN { if (r <= 0) exit 1; printf "%.6f", 1.0 / r }')"
  safe_rate="${rate//./p}"
  csv="${OUTDIR}/raw/rps_${safe_rate}.csv"
  log="${OUTDIR}/logs/rps_${safe_rate}.log"
  rate_warmup_csv="${OUTDIR}/raw/rps_${safe_rate}_pre_warmup.csv"
  rate_warmup_log="${OUTDIR}/logs/rps_${safe_rate}_pre_warmup.log"

  echo
  echo "[INFO] Wait for health before rate=${rate} rps"
  for _ in $(seq 1 60); do
    code="$(curl -sS -o /dev/null \
      --connect-timeout 1 \
      --max-time 2 \
      -w "%{http_code}" \
      "http://${WORKER_IP}:${PORT}/healthz" 2>/dev/null || echo "000")"
    if [ "${code}" = "200" ]; then
      break
    fi
    sleep 1
  done

  if [ "${RATE_WARMUP_SECONDS}" != "0" ]; then
    echo "[INFO] Pre-rate warmup ${RATE_WARMUP_SECONDS}s at 1 rps for rate=${rate}"
    "${PYTHON_BIN}" "${CLIENT}" \
      --url "http://${WORKER_IP}:${PORT}/infer" \
      --image "${IMAGE_PATH}" \
      --seconds "${RATE_WARMUP_SECONDS}" \
      --interval 1 \
      --csv "${rate_warmup_csv}" \
      > "${rate_warmup_log}" 2>&1
  fi

  echo
  echo "[INFO] Test rate=${rate} rps interval=${interval}s duration=${DURATION}s"
  "${PYTHON_BIN}" "${CLIENT}" \
    --url "http://${WORKER_IP}:${PORT}/infer" \
    --image "${IMAGE_PATH}" \
    --seconds "${DURATION}" \
    --interval "${interval}" \
    --csv "${csv}" \
    > "${log}" 2>&1

  RATE="${rate}" INTERVAL="${interval}" DURATION="${DURATION}" CSV="${csv}" SUMMARY_CSV="${SUMMARY_CSV}" "${PYTHON_BIN}" - <<'PY'
import csv
import math
import os
from collections import Counter
from pathlib import Path

import pandas as pd

rate = os.environ["RATE"]
interval = os.environ["INTERVAL"]
path = Path(os.environ["CSV"])
summary = Path(os.environ["SUMMARY_CSV"])
duration = float(os.environ["DURATION"])

df = pd.read_csv(path)
total = int(len(df))
success = int(df.get("success", pd.Series(dtype=int)).fillna(0).astype(int).sum())
failures = total - success
success_rate = (success / total * 100.0) if total else 0.0
achieved_rps = (total / duration) if duration > 0 else 0.0

codes = Counter(str(x) for x in df.get("status_code", pd.Series(dtype=str)).fillna("").astype(str))
status_codes = ";".join(f"{k}:{v}" for k, v in sorted(codes.items()))

def metric(col, kind):
    if col not in df:
        return ""
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if s.empty:
        return ""
    if kind == "mean":
        return f"{s.mean():.3f}"
    if kind == "p95":
        return f"{s.quantile(0.95):.3f}"
    if kind == "p99":
        return f"{s.quantile(0.99):.3f}"
    if kind == "max":
        return f"{s.max():.3f}"
    raise ValueError(kind)

row = [
    rate,
    f"{achieved_rps:.6f}",
    interval,
    total,
    success,
    failures,
    f"{success_rate:.6f}",
    status_codes,
    metric("latency_ms_client", "mean"),
    metric("latency_ms_client", "p95"),
    metric("latency_ms_client", "p99"),
    metric("latency_ms_client", "max"),
    metric("server_latency_ms", "mean"),
    metric("server_latency_ms", "p95"),
    metric("server_latency_ms", "p99"),
    metric("server_latency_ms", "max"),
]

with summary.open("a", newline="") as f:
    csv.writer(f).writerow(row)

print(f"[SUMMARY] rps={rate} total={total} success={success} failures={failures} success_rate={success_rate:.6f}%")
PY

  if [ "${COOLDOWN_SECONDS}" != "0" ]; then
    sleep "${COOLDOWN_SECONDS}"
  fi
done

kubectl -n "${NS}" get pods -l app=yolo26n -o wide | tee "${OUTDIR}/k8s/pods_after_sweep.txt"

echo
echo "[INFO] Done"
echo "[INFO] Summary: ${SUMMARY_CSV}"
echo "[INFO] No-failure candidates:"
awk -F, 'NR == 1 || $6 == 0 { print }' "${SUMMARY_CSV}" | tee "${OUTDIR}/summary/no_failure_candidates.csv"
