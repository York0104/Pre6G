#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:-${RUN_ID:?missing run id}}"

AUTOSCALE_DIR="${AUTOSCALE_DIR:-$HOME/AutoScale}"
OUT_DIR="${OUT_DIR:-$HOME/exp_runs/$RUN_ID}"

WORKER_HOST="${WORKER_HOST:-100.105.48.97}"
WORKER_USER="${WORKER_USER:-icclz1}"
WORKER_REPO="${WORKER_REPO:-/home/icclz1/gpu-tempctl-lab}"
WORKER_SSH="${WORKER_USER}@${WORKER_HOST}"
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5"

TARGET_C="${TARGET_TEMP_C:-${TARGET_TEMP:-${TARGET:-90}}}"
BAND="${BAND:-3}"
WARMUP_SECONDS="${WARMUP_SECONDS:-0}"
NORMAL_HOLD_SECONDS="${NORMAL_HOLD_SECONDS:-0}"
FAULT_HOLD_SECONDS="${FAULT_HOLD_SECONDS:-1800}"
STABLE_SECONDS="${STABLE_SECONDS:-20}"
SAMPLE_INTERVAL="${SAMPLE_INTERVAL:-1.0}"
MIN_DWELL_SECONDS="${MIN_DWELL_SECONDS:-15}"
THERMAL_CONTROL_MODE="${THERMAL_CONTROL_MODE:-supervisor}"
FIXED_FAN_PCT="${FIXED_FAN_PCT:-5}"

BASELINE_MODE="${BASELINE_MODE:-GPU_DEFAULT}"
FAULT_START_MODE="${FAULT_START_MODE:-GPU_FAULT_5}"
RESTORE_MODE="${RESTORE_MODE:-GPU_DEFAULT}"
CC_PASSWORD="${CC_PASSWORD:-}"

mkdir -p "$OUT_DIR"

echo "RUN_ID=$RUN_ID"
echo "OUT_DIR=$OUT_DIR"
echo "WORKER_SSH=$WORKER_SSH"
echo "TARGET_C=$TARGET_C"
echo "BAND=$BAND"
echo "WARMUP_SECONDS=$WARMUP_SECONDS"
echo "NORMAL_HOLD_SECONDS=$NORMAL_HOLD_SECONDS"
echo "FAULT_HOLD_SECONDS=$FAULT_HOLD_SECONDS"
echo "FAULT_START_MODE=$FAULT_START_MODE"
echo "THERMAL_CONTROL_MODE=$THERMAL_CONTROL_MODE"
echo "FIXED_FAN_PCT=$FIXED_FAN_PCT"

if [[ -z "$CC_PASSWORD" ]]; then
  echo "missing CC_PASSWORD"
  exit 1
fi

ssh ${SSH_OPTS} "${WORKER_SSH}" "
  hostname
  whoami
  test -d '${WORKER_REPO}'
  nvidia-smi --query-gpu=name,temperature.gpu,fan.speed,power.draw --format=csv
"

if [[ "${THERMAL_CONTROL_MODE}" == "fixed_manual" ]]; then
  TOTAL_SECONDS="$((WARMUP_SECONDS + NORMAL_HOLD_SECONDS + FAULT_HOLD_SECONDS))"
  ssh ${SSH_OPTS} "${WORKER_SSH}" bash -s -- \
    "${WORKER_REPO}" \
    "${RUN_ID}" \
    "${CC_PASSWORD}" \
    "${FIXED_FAN_PCT}" \
    "${RESTORE_MODE}" \
    "${TARGET_C}" \
    "${BAND}" \
    "${TOTAL_SECONDS}" \
    "${SAMPLE_INTERVAL}" > "$OUT_DIR/worker_run.log" 2>&1 <<'REMOTE'
set -euo pipefail

WORKER_REPO="$1"
RUN_ID="$2"
CC_PASSWORD="$3"
FIXED_FAN_PCT="$4"
RESTORE_MODE="$5"
TARGET_C="$6"
BAND="$7"
TOTAL_SECONDS="$8"
SAMPLE_INTERVAL="$9"

cd "$WORKER_REPO"
source ../gpu-tempctl-1080ti/bin/activate
source fan_control_lab/env.sh
source "$HOME/.cargo/env"
export CCTV_DAEMON_PASSWORD="$CC_PASSWORD"
export MPLCONFIGDIR="$HOME/.config/matplotlib"
mkdir -p "$MPLCONFIGDIR"

LOG_DIR="$WORKER_REPO/fan_control_lab/logs/$RUN_ID"
mkdir -p "$LOG_DIR"

cleanup() {
  python fan_control_lab/cc.py -p "$CC_PASSWORD" --mode "$RESTORE_MODE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

python fan_control_lab/cc.py -p "$CC_PASSWORD" -m NVIDIA -c fan --speed "$FIXED_FAN_PCT"

python - "$LOG_DIR" "$FIXED_FAN_PCT" "$TARGET_C" "$BAND" "$TOTAL_SECONDS" "$SAMPLE_INTERVAL" "$RESTORE_MODE" <<'PY'
import csv
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

log_dir = Path(sys.argv[1])
fixed_fan_pct = float(sys.argv[2])
target_c = float(sys.argv[3])
band_c = float(sys.argv[4])
total_seconds = float(sys.argv[5])
sample_interval = float(sys.argv[6])
restore_mode = sys.argv[7]

thermal_path = log_dir / "thermal.csv"
events_path = log_dir / "events.csv"
meta_path = log_dir / "metadata.json"

fieldnames = [
    "timestamp",
    "elapsed_s",
    "phase",
    "binary_label",
    "phase_elapsed_s",
    "gpu_temp_c",
    "gpu_state",
    "gpu_util_pct",
    "gpu_power_w",
    "gpu_fan_pct",
    "gpu_clock_mhz",
    "gpu_mem_clock_mhz",
    "current_mode",
    "desired_mode",
    "reason",
    "infeasible",
    "target_temp_c",
    "band_c",
    "stable_counter_s",
]

with meta_path.open("w", encoding="utf-8") as fh:
    json.dump(
        {
            "run_id": log_dir.name,
            "control_mode": "fixed_manual",
            "fixed_fan_pct": fixed_fan_pct,
            "restore_mode": restore_mode,
            "total_seconds": total_seconds,
            "sample_interval": sample_interval,
        },
        fh,
        indent=2,
    )

with events_path.open("w", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    writer.writerow(["timestamp", "elapsed_s", "phase", "event", "detail"])
    writer.writerow([datetime.now().isoformat(timespec="seconds"), 0.0, "fault_hold", "set_manual_fan", f"{fixed_fan_pct}%"])

start = time.time()

with thermal_path.open("w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=fieldnames)
    writer.writeheader()
    while True:
        now = time.time()
        elapsed = now - start
        if elapsed > total_seconds:
            break

        raw = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=timestamp,temperature.gpu,utilization.gpu,power.draw,fan.speed,clocks.sm,clocks.mem",
                "--format=csv,noheader,nounits",
            ],
            text=True,
        ).strip()
        line = raw.splitlines()[0]
        parts = [x.strip() for x in line.split(",")]

        temp = float(parts[1])
        state = "below_band"
        if temp > target_c + band_c:
            state = "above_band"
        elif target_c - band_c <= temp <= target_c + band_c:
            state = "within_band"

        writer.writerow(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "elapsed_s": round(elapsed, 3),
                "phase": "fault_hold",
                "binary_label": "fault",
                "phase_elapsed_s": round(elapsed, 3),
                "gpu_temp_c": temp,
                "gpu_state": state,
                "gpu_util_pct": float(parts[2]),
                "gpu_power_w": float(parts[3]),
                "gpu_fan_pct": float(parts[4]),
                "gpu_clock_mhz": float(parts[5]),
                "gpu_mem_clock_mhz": float(parts[6]),
                "current_mode": f"MANUAL_FIXED_{int(fixed_fan_pct)}",
                "desired_mode": f"MANUAL_FIXED_{int(fixed_fan_pct)}",
                "reason": "fixed_fan_manual",
                "infeasible": "",
                "target_temp_c": target_c,
                "band_c": band_c,
                "stable_counter_s": 0.0,
            }
        )
        fh.flush()
        time.sleep(sample_interval)

with events_path.open("a", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    writer.writerow([datetime.now().isoformat(timespec="seconds"), round(time.time() - start, 3), "finalize", "restore_mode", restore_mode])
PY
REMOTE
else
  ssh ${SSH_OPTS} "${WORKER_SSH}" "
    cd ${WORKER_REPO} &&
    source ../gpu-tempctl-1080ti/bin/activate &&
    source fan_control_lab/env.sh &&
    source \$HOME/.cargo/env &&
    export CCTV_DAEMON_PASSWORD='${CC_PASSWORD}' &&
    export MPLCONFIGDIR=\$HOME/.config/matplotlib &&
    mkdir -p \$MPLCONFIGDIR &&
    python fan_control_lab/gpu_cycle_runner.py \
      --tag ${RUN_ID} \
      --target ${TARGET_C} \
      --band ${BAND} \
      --crit-temp 95 \
      --warmup-seconds ${WARMUP_SECONDS} \
      --normal-hold-seconds ${NORMAL_HOLD_SECONDS} \
      --fault-hold-seconds ${FAULT_HOLD_SECONDS} \
      --stable-seconds ${STABLE_SECONDS} \
      --sample-interval ${SAMPLE_INTERVAL} \
      --min-dwell-seconds ${MIN_DWELL_SECONDS} \
      --size 4096 \
      --duty 1.0 \
      --period-ms 100 \
      --baseline-mode ${BASELINE_MODE} \
      --fault-start-mode ${FAULT_START_MODE} \
      --restore-mode ${RESTORE_MODE}
  " > "$OUT_DIR/worker_run.log" 2>&1
fi

mkdir -p "$OUT_DIR/worker_logs"
rsync -e "ssh ${SSH_OPTS}" -av \
  "${WORKER_SSH}:${WORKER_REPO}/fan_control_lab/logs/${RUN_ID}/" \
  "$OUT_DIR/worker_logs/"

python "$AUTOSCALE_DIR/experiments/thermal_analysis/live_cycle_plot.py" \
  --csv "$OUT_DIR/worker_logs/thermal.csv" \
  --out "$OUT_DIR/final_plot.png" \
  --target "$TARGET_C" \
  --band "$BAND" \
  --title "Final Thermal Curve - ${RUN_ID}" >/dev/null 2>&1 || true

python "$AUTOSCALE_DIR/experiments/thermal_analysis/merge_run.py" \
  --run-dir "$OUT_DIR" >/dev/null 2>&1 || true

echo "完成：$OUT_DIR"
