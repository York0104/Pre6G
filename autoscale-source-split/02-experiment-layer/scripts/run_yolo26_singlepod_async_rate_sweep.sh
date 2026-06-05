#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_LAYER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPLIT_ROOT="$(cd "${EXPERIMENT_LAYER_DIR}/.." && pwd)"
PRE6G_ROOT="$(cd "${SPLIT_ROOT}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${PRE6G_ROOT}/iccl/bin/python}"

RUN_ID="${1:-single_yolo26_async_rate_sweep_$(date +%Y%m%d_%H%M%S)}"
OUTDIR="${OUTDIR:-${HOME}/exp_runs/${RUN_ID}}"

NS="${NS:-intent-lab}"
DEPLOY="${DEPLOY:-yolo26n-focus}"
WORKER_IP="${WORKER_IP:-140.113.179.6}"
PORT="${PORT:-18081}"
DURATION="${DURATION:-180}"
CONCURRENCY="${CONCURRENCY:-200}"
WARMUP_SECONDS="${WARMUP_SECONDS:-20}"
RATE_WARMUP_SECONDS="${RATE_WARMUP_SECONDS:-10}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-30}"
RATES_RPS="${RATES_RPS:-15,20,30,50,100}"

IMAGE_PATH="${TEST_IMAGE:-${EXPERIMENT_LAYER_DIR}/yolo26_workload/test_images/sanity_input.png}"
CLIENT="${CLIENT:-${EXPERIMENT_LAYER_DIR}/thermal_analysis/yolo26_async_openloop_client.py}"

mkdir -p "${OUTDIR}/raw" "${OUTDIR}/logs" "${OUTDIR}/k8s" "${OUTDIR}/summary"

echo "[INFO] RUN_ID=${RUN_ID}"
echo "[INFO] OUTDIR=${OUTDIR}"
echo "[INFO] target=http://${WORKER_IP}:${PORT}/infer"
echo "[INFO] RATES_RPS=${RATES_RPS}"
echo "[INFO] DURATION=${DURATION}"
echo "[INFO] CONCURRENCY=${CONCURRENCY}"

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
  --rate-rps 1 \
  --concurrency "${CONCURRENCY}" \
  --csv "${OUTDIR}/raw/warmup.csv" \
  > "${OUTDIR}/logs/warmup.log" 2>&1

SUMMARY_CSV="${OUTDIR}/summary/async_rate_sweep_summary.csv"
echo "rate_rps,attempted_rps,successful_rps,total,success,failures,success_rate_pct,status_codes,client_latency_ms_mean,client_latency_ms_p95,client_latency_ms_p99,client_latency_ms_max,schedule_lag_ms_p95,queue_delay_ms_p95,server_latency_ms_mean,server_latency_ms_p95,server_latency_ms_p99,server_latency_ms_max" > "${SUMMARY_CSV}"

IFS=',' read -r -a RATE_LIST <<< "${RATES_RPS}"
for rate in "${RATE_LIST[@]}"; do
  rate="$(echo "${rate}" | xargs)"
  if [ -z "${rate}" ]; then
    continue
  fi

  safe_rate="${rate//./p}"
  csv="${OUTDIR}/raw/rps_${safe_rate}.csv"
  log="${OUTDIR}/logs/rps_${safe_rate}.log"

  echo
  echo "[INFO] Wait for health before async rate=${rate} rps"
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
    echo "[INFO] Pre-rate async warmup ${RATE_WARMUP_SECONDS}s at 1 rps for rate=${rate}"
    "${PYTHON_BIN}" "${CLIENT}" \
      --url "http://${WORKER_IP}:${PORT}/infer" \
      --image "${IMAGE_PATH}" \
      --seconds "${RATE_WARMUP_SECONDS}" \
      --rate-rps 1 \
      --concurrency "${CONCURRENCY}" \
      --csv "${OUTDIR}/raw/rps_${safe_rate}_pre_warmup.csv" \
      > "${OUTDIR}/logs/rps_${safe_rate}_pre_warmup.log" 2>&1
  fi

  echo "[INFO] Test async open-loop rate=${rate} rps duration=${DURATION}s concurrency=${CONCURRENCY}"
  "${PYTHON_BIN}" "${CLIENT}" \
    --url "http://${WORKER_IP}:${PORT}/infer" \
    --image "${IMAGE_PATH}" \
    --seconds "${DURATION}" \
    --rate-rps "${rate}" \
    --concurrency "${CONCURRENCY}" \
    --csv "${csv}" \
    > "${log}" 2>&1

  RATE="${rate}" DURATION="${DURATION}" CSV="${csv}" SUMMARY_CSV="${SUMMARY_CSV}" "${PYTHON_BIN}" - <<'PY'
import csv
import math
import os
from collections import Counter
from pathlib import Path

rate = os.environ["RATE"]
duration = float(os.environ["DURATION"])
path = Path(os.environ["CSV"])
summary = Path(os.environ["SUMMARY_CSV"])

def to_float(x):
    try:
        return float(x)
    except Exception:
        return math.nan

def quantile(vals, q):
    vals = sorted(v for v in vals if not math.isnan(v))
    if not vals:
        return ""
    idx = min(len(vals) - 1, max(0, math.ceil(q * len(vals)) - 1))
    return f"{vals[idx]:.3f}"

def mean(vals):
    vals = [v for v in vals if not math.isnan(v)]
    return f"{(sum(vals) / len(vals)):.3f}" if vals else ""

rows = list(csv.DictReader(path.open()))
total = len(rows)
success = sum(1 for row in rows if row.get("success") == "1")
failures = total - success
success_rate = (success / total * 100.0) if total else 0.0
attempted_rps = total / duration if duration > 0 else 0.0
successful_rps = success / duration if duration > 0 else 0.0
codes = Counter(row.get("status_code", "") for row in rows)
status_codes = ";".join(f"{k}:{v}" for k, v in sorted(codes.items()))

client = [to_float(row.get("latency_ms_client", "")) for row in rows]
lag = [to_float(row.get("schedule_lag_ms", "")) for row in rows]
queue = [to_float(row.get("queue_delay_ms", "")) for row in rows]
server = [to_float(row.get("server_latency_ms", "")) for row in rows]

out = [
    rate,
    f"{attempted_rps:.6f}",
    f"{successful_rps:.6f}",
    total,
    success,
    failures,
    f"{success_rate:.6f}",
    status_codes,
    mean(client),
    quantile(client, 0.95),
    quantile(client, 0.99),
    quantile(client, 1.0),
    quantile(lag, 0.95),
    quantile(queue, 0.95),
    mean(server),
    quantile(server, 0.95),
    quantile(server, 0.99),
    quantile(server, 1.0),
]

with summary.open("a", newline="") as f:
    csv.writer(f).writerow(out)

print(
    f"[SUMMARY] rps={rate} attempted_rps={attempted_rps:.6f} "
    f"successful_rps={successful_rps:.6f} success={success} failures={failures}"
)
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
