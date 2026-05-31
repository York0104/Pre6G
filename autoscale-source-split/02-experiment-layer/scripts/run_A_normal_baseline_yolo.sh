#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_LAYER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUN_ID="${1:-A_normal_yolo26s_$(date +%Y%m%d_%H%M%S)}"
OUTDIR="${OUTDIR:-$HOME/exp_runs/$RUN_ID}"

NS="${NS:-intent-lab}"
WORKER_IP="${WORKER_IP:-140.113.179.6}"

DURATION="${DURATION:-600}"
FOCUS_INTERVAL="${FOCUS_INTERVAL:-0.1}"
BG_INTERVAL="${BG_INTERVAL:-0.2}"
WARMUP_N="${WARMUP_N:-30}"

PORT1="${PORT1:-18081}"
PORT2="${PORT2:-18082}"
PORT3="${PORT3:-18083}"

mkdir -p "$OUTDIR"/{k8s_logs,network_check,client_logs,warmup,summary}

echo "======================================"
echo "A. Normal Baseline"
echo "RUN_ID=$RUN_ID"
echo "OUTDIR=$OUTDIR"
echo "WORKER_IP=$WORKER_IP"
echo "DURATION=$DURATION"
echo "FOCUS_INTERVAL=$FOCUS_INTERVAL"
echo "BG_INTERVAL=$BG_INTERVAL"
echo "WARMUP_N=$WARMUP_N"
echo "======================================"
echo

echo "=== Kubernetes nodes ==="
kubectl get nodes -o wide | tee "$OUTDIR/k8s_logs/nodes.txt"
echo

echo "=== intent-lab pods ==="
kubectl get pods -n "$NS" -o wide | egrep 'focus|bg|NAME' | tee "$OUTDIR/k8s_logs/pods.txt"
echo

echo "=== deployment env ==="
for d in yolo26n-focus yolo26n-bg-1 yolo26n-bg-2; do
  echo "========== $d ==========" | tee -a "$OUTDIR/k8s_logs/deploy_env.txt"
  kubectl -n "$NS" exec deploy/$d -- sh -lc \
    'printenv | egrep -i "YOLO|MODEL|WEIGHT|IMGSZ|DEVICE|NVIDIA_VISIBLE_DEVICES" || true' \
    | tee -a "$OUTDIR/k8s_logs/deploy_env.txt"
done
echo

IMAGE_PATH="${TEST_IMAGE:-${EXPERIMENT_LAYER_DIR}/yolo26_workload/test_images/sanity_input.png}"

if [ ! -f "$IMAGE_PATH" ]; then
  echo "[ERR] 找不到測試圖片: $IMAGE_PATH"
  exit 1
fi

echo "IMAGE_PATH=$IMAGE_PATH" | tee "$OUTDIR/image_path.txt"
echo

echo "=== pre healthz check ==="
for port in "$PORT1" "$PORT2" "$PORT3"; do
  echo "=== $WORKER_IP:$port ===" | tee -a "$OUTDIR/network_check/pre_healthz.txt"
  curl -sS -o /dev/null \
    --connect-timeout 2 \
    --max-time 5 \
    -w "http_code=%{http_code} connect=%{time_connect} starttransfer=%{time_starttransfer} total=%{time_total}\n" \
    "http://${WORKER_IP}:${port}/healthz" \
    | tee -a "$OUTDIR/network_check/pre_healthz.txt" || true
done
echo

echo "=== warmup infer ==="
for port in "$PORT1" "$PORT2" "$PORT3"; do
  echo "=== warmup port $port ===" | tee "$OUTDIR/warmup/warmup_${port}.log"

  for i in $(seq 1 "$WARMUP_N"); do
    tmp=$(mktemp)
    curl -sS -o /dev/null \
      --connect-timeout 2 \
      --max-time 15 \
      -w "warmup_port=$port iter=$i http_code=%{http_code} total=%{time_total}\n" \
      -F "file=@${IMAGE_PATH}" \
      "http://${WORKER_IP}:${port}/infer" \
      > "$tmp" 2>> "$OUTDIR/warmup/warmup_${port}.err"

    rc=$?
    if [ "$rc" -eq 0 ]; then
      cat "$tmp" | tee -a "$OUTDIR/warmup/warmup_${port}.log"
    else
      out=$(cat "$tmp")
      if [ -n "$out" ]; then
        echo "$out curl_exit=$rc" | tee -a "$OUTDIR/warmup/warmup_${port}.log"
      else
        echo "warmup_port=$port iter=$i http_code=000 total=15.000 curl_exit=$rc" | tee -a "$OUTDIR/warmup/warmup_${port}.log"
      fi
    fi
    rm -f "$tmp"

    sleep 0.2
  done
done
echo

echo "=== after warmup healthz check ==="
for port in "$PORT1" "$PORT2" "$PORT3"; do
  echo "=== $WORKER_IP:$port ===" | tee -a "$OUTDIR/network_check/after_warmup_healthz.txt"
  curl -sS -o /dev/null \
    --connect-timeout 2 \
    --max-time 5 \
    -w "http_code=%{http_code} connect=%{time_connect} starttransfer=%{time_starttransfer} total=%{time_total}\n" \
    "http://${WORKER_IP}:${port}/healthz" \
    | tee -a "$OUTDIR/network_check/after_warmup_healthz.txt" || true
done
echo

HEALTH_CSV="$OUTDIR/network_check/healthz_live.csv"

cat > "$OUTDIR/network_check/live_healthz_watch.sh" <<'EOF'
#!/usr/bin/env bash
WORKER_IP="$1"
OUT="$2"
shift 2
PORTS="$@"

echo "ts,port,http_code,connect_ms,starttransfer_ms,total_ms,success" > "$OUT"

while true; do
  for port in $PORTS; do
    ts=$(date "+%Y-%m-%dT%H:%M:%S.%3N")

    line=$(curl -sS -o /dev/null \
      --connect-timeout 2 \
      --max-time 5 \
      -w "%{http_code},%{time_connect},%{time_starttransfer},%{time_total}" \
      "http://${WORKER_IP}:${port}/healthz" 2>/dev/null || echo "000,0,0,5")

    code=$(echo "$line" | cut -d',' -f1)
    connect=$(echo "$line" | cut -d',' -f2)
    starttransfer=$(echo "$line" | cut -d',' -f3)
    total=$(echo "$line" | cut -d',' -f4)

    if [ "$code" = "200" ]; then
      success=1
    else
      success=0
    fi

    awk -v ts="$ts" -v port="$port" -v code="$code" \
        -v c="$connect" -v s="$starttransfer" -v t="$total" -v ok="$success" \
        'BEGIN { printf "%s,%s,%s,%.3f,%.3f,%.3f,%s\n", ts, port, code, c*1000, s*1000, t*1000, ok }' \
        >> "$OUT"
  done
  sleep "${HEALTH_INTERVAL:-1.0}"
done
EOF

chmod +x "$OUTDIR/network_check/live_healthz_watch.sh"

"$OUTDIR/network_check/live_healthz_watch.sh" "$WORKER_IP" "$HEALTH_CSV" "$PORT1" "$PORT2" "$PORT3" &
WATCH_PID=$!
echo "$WATCH_PID" > "$OUTDIR/network_check/healthz_watch.pid"

PY=python
command -v python >/dev/null || PY=python3

echo "=== start latency clients ==="

$PY "${EXPERIMENT_LAYER_DIR}/thermal_analysis/yolo26_latency_client_stable.py" \
  --url "http://${WORKER_IP}:${PORT1}/infer" \
  --image "$IMAGE_PATH" \
  --seconds "$DURATION" \
  --interval "$FOCUS_INTERVAL" \
  --csv "$OUTDIR/focus_inst1.csv" \
  > "$OUTDIR/client_logs/focus_inst1.stdout.log" 2>&1 &
PID1=$!

$PY "${EXPERIMENT_LAYER_DIR}/thermal_analysis/yolo26_latency_client_stable.py" \
  --url "http://${WORKER_IP}:${PORT2}/infer" \
  --image "$IMAGE_PATH" \
  --seconds "$DURATION" \
  --interval "$BG_INTERVAL" \
  --csv "$OUTDIR/bg_inst2.csv" \
  > "$OUTDIR/client_logs/bg_inst2.stdout.log" 2>&1 &
PID2=$!

$PY "${EXPERIMENT_LAYER_DIR}/thermal_analysis/yolo26_latency_client_stable.py" \
  --url "http://${WORKER_IP}:${PORT3}/infer" \
  --image "$IMAGE_PATH" \
  --seconds "$DURATION" \
  --interval "$BG_INTERVAL" \
  --csv "$OUTDIR/bg_inst3.csv" \
  > "$OUTDIR/client_logs/bg_inst3.stdout.log" 2>&1 &
PID3=$!

wait "$PID1"; RC1=$?
wait "$PID2"; RC2=$?
wait "$PID3"; RC3=$?

kill "$WATCH_PID" 2>/dev/null || true
sleep 1

echo "$RC1" > "$OUTDIR/client_logs/focus_inst1.exit_code"
echo "$RC2" > "$OUTDIR/client_logs/bg_inst2.exit_code"
echo "$RC3" > "$OUTDIR/client_logs/bg_inst3.exit_code"

OUTDIR="$OUTDIR" python3 - <<'PY'
import csv
import math
import os
import re
import statistics
from pathlib import Path

outdir = Path(os.environ["OUTDIR"])
summary_dir = outdir / "summary"
summary_dir.mkdir(exist_ok=True)

files = ["focus_inst1.csv", "bg_inst2.csv", "bg_inst3.csv"]
rows = []


def quantile(values, q):
    if not values:
        return float("nan")
    values = sorted(values)
    if len(values) == 1:
        return float(values[0])
    pos = (len(values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(values[lo])
    return float(values[lo] + (values[hi] - values[lo]) * (pos - lo))


def is_success(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


for name in files:
    f = outdir / name
    if not f.exists():
        rows.append({
            "file": name,
            "total": 0,
            "success": 0,
            "fail": 0,
            "success_rate_pct": 0.0,
            "client_mean_ms": float("nan"),
            "client_p50_ms": float("nan"),
            "client_p95_ms": float("nan"),
            "client_p99_ms": float("nan"),
            "client_max_ms": float("nan"),
            "server_mean_ms": float("nan"),
            "server_p95_ms": float("nan"),
            "server_p99_ms": float("nan"),
            "server_max_ms": float("nan"),
            "client_latency_gt_1s": -1,
            "client_latency_gt_5s": -1,
            "missing_csv": 1,
        })
        continue

    with f.open(newline="") as fh:
        data = list(csv.DictReader(fh))

    total = len(data)
    ok_rows = [r for r in data if is_success(r.get("success", "0"))]
    success = len(ok_rows)
    fail = total - success

    def parse_float(row, key):
        raw = row.get(key, "")
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except Exception:
            return None

    lat = [x for x in (parse_float(r, "latency_ms_client") for r in ok_rows) if x is not None]
    srv = [x for x in (parse_float(r, "server_latency_ms") for r in ok_rows) if x is not None]

    rows.append({
        "file": name,
        "total": total,
        "success": success,
        "fail": fail,
        "success_rate_pct": round(success / total * 100, 3) if total else 0.0,
        "client_mean_ms": round(statistics.mean(lat), 3) if lat else float("nan"),
        "client_p50_ms": round(quantile(lat, 0.50), 3),
        "client_p95_ms": round(quantile(lat, 0.95), 3),
        "client_p99_ms": round(quantile(lat, 0.99), 3),
        "client_max_ms": round(max(lat), 3) if lat else float("nan"),
        "server_mean_ms": round(statistics.mean(srv), 3) if srv else float("nan"),
        "server_p95_ms": round(quantile(srv, 0.95), 3),
        "server_p99_ms": round(quantile(srv, 0.99), 3),
        "server_max_ms": round(max(srv), 3) if srv else float("nan"),
        "client_latency_gt_1s": sum(1 for x in lat if x > 1000),
        "client_latency_gt_5s": sum(1 for x in lat if x > 5000),
        "missing_csv": 0,
    })

columns = [
    "file", "total", "success", "fail", "success_rate_pct",
    "client_mean_ms", "client_p50_ms", "client_p95_ms", "client_p99_ms", "client_max_ms",
    "server_mean_ms", "server_p95_ms", "server_p99_ms", "server_max_ms",
    "client_latency_gt_1s", "client_latency_gt_5s", "missing_csv",
]

summary_csv = summary_dir / "latency_summary.csv"
summary_txt = summary_dir / "latency_summary.txt"
with summary_csv.open("w", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

header = " ".join(columns)
lines = [header]
for row in rows:
    lines.append(" ".join(str(row[c]) for c in columns))
summary_txt.write_text("\n".join(lines) + "\n")

health_csv = outdir / "network_check" / "healthz_live.csv"
health_fail_total = 0
if health_csv.exists():
    with health_csv.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("success", "0")) != "1":
                health_fail_total += 1
else:
    health_fail_total = -1

warmup_fail_total = 0
for wf in sorted((outdir / "warmup").glob("warmup_*.log")):
    text = wf.read_text(errors="ignore").splitlines()
    for line in text:
        m = re.search(r"http_code=(\d+)", line)
        if m and m.group(1) != "200":
            warmup_fail_total += 1
        if "curl_exit=" in line:
            warmup_fail_total += 1

clean = True
clean &= len(rows) == 3
clean &= all(r["missing_csv"] == 0 for r in rows)
clean &= all(r["success_rate_pct"] >= 99.999 for r in rows)
clean &= all(r["client_latency_gt_1s"] == 0 for r in rows)
clean &= all(r["client_latency_gt_5s"] == 0 for r in rows)
clean &= all((not math.isnan(r["client_max_ms"])) and r["client_max_ms"] <= 500 for r in rows)
clean &= health_fail_total == 0
clean &= warmup_fail_total == 0

validity_txt = summary_dir / "run_validity.txt"
validity_txt.write_text(
    f"clean_normal_candidate={clean}\n"
    f"health_fail_total={health_fail_total}\n"
    f"warmup_fail_total={warmup_fail_total}\n"
    "criteria=success_rate_100pct,no_client_latency_gt_1s,no_healthz_fail,no_warmup_fail,client_max_le_500ms\n"
)

print()
print("======================================")
print("RESULT SUMMARY")
print("======================================")
for line in lines:
    print(line)
print()
print(f"health_fail_total={health_fail_total}")
print(f"warmup_fail_total={warmup_fail_total}")
print(f"clean_normal_candidate={clean}")
print()
print(f"OUTDIR={outdir}")
print(f"summary_csv={summary_csv}")
print(f"summary_txt={summary_txt}")
print(f"validity_txt={validity_txt}")
PY