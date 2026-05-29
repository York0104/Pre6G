#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:-${RUN_ID:?missing run id}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
AUTOSCALE_DIR="${AUTOSCALE_DIR:-$REPO_ROOT/autoscale-source-split/02-experiment-layer}"
OUT_DIR="${OUT_DIR:-$HOME/exp_runs/$RUN_ID}"

WORKER_HOST="${WORKER_HOST:-140.113.179.6}"
WORKER_USER="${WORKER_USER:-icclz1}"
WORKER_REPO="${WORKER_REPO:-/home/icclz1/gpu-tempctl-lab}"
WORKER_SSH_ALIAS="${WORKER_SSH_ALIAS:-icclz1-gpu}"
WORKER_SSH="${WORKER_SSH:-$WORKER_SSH_ALIAS}"
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5"

CYCLES="${CYCLES:-3}"
NORMAL_HOLD_SECONDS="${NORMAL_HOLD_SECONDS:-900}"
FAULT_HOLD_SECONDS="${FAULT_HOLD_SECONDS:-900}"
RECOVERY_STABLE_SECONDS="${RECOVERY_STABLE_SECONDS:-60}"
RECOVERY_MAX_SECONDS="${RECOVERY_MAX_SECONDS:-900}"
SAMPLE_INTERVAL="${SAMPLE_INTERVAL:-1.0}"
BASELINE_MODE="${BASELINE_MODE:-GPU_DEFAULT}"
RESTORE_MODE="${RESTORE_MODE:-GPU_DEFAULT}"
FIXED_FAN_PCT="${FIXED_FAN_PCT:-5}"
CC_PASSWORD="${CC_PASSWORD:-nctuiiot}"

NORMAL_TEMP_MIN_C="${NORMAL_TEMP_MIN_C:-50}"
NORMAL_TEMP_MAX_C="${NORMAL_TEMP_MAX_C:-70}"
FAULT_TEMP_TARGET_C="${FAULT_TEMP_TARGET_C:-90}"

BG_SIZE="${BG_SIZE:-4096}"
BG_DUTY="${BG_DUTY:-1.0}"
BG_PERIOD_MS="${BG_PERIOD_MS:-100}"
WORKLOAD_HEADROOM_SECONDS="${WORKLOAD_HEADROOM_SECONDS:-300}"

mkdir -p "$OUT_DIR"

echo "RUN_ID=$RUN_ID"
echo "OUT_DIR=$OUT_DIR"
echo "WORKER_SSH=$WORKER_SSH"
echo "CYCLES=$CYCLES"
echo "NORMAL_HOLD_SECONDS=$NORMAL_HOLD_SECONDS"
echo "FAULT_HOLD_SECONDS=$FAULT_HOLD_SECONDS"
echo "RECOVERY_STABLE_SECONDS=$RECOVERY_STABLE_SECONDS"
echo "RECOVERY_MAX_SECONDS=$RECOVERY_MAX_SECONDS"
echo "FIXED_FAN_PCT=$FIXED_FAN_PCT"
echo "NORMAL_TEMP_MIN_C=$NORMAL_TEMP_MIN_C"
echo "NORMAL_TEMP_MAX_C=$NORMAL_TEMP_MAX_C"
echo "FAULT_TEMP_TARGET_C=$FAULT_TEMP_TARGET_C"
echo "BG_SIZE=$BG_SIZE"
echo "BG_DUTY=$BG_DUTY"
echo "BG_PERIOD_MS=$BG_PERIOD_MS"

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

ssh ${SSH_OPTS} "${WORKER_SSH}" bash -s -- \
  "${WORKER_REPO}" \
  "${RUN_ID}" \
  "${CC_PASSWORD}" \
  "${CYCLES}" \
  "${NORMAL_HOLD_SECONDS}" \
  "${FAULT_HOLD_SECONDS}" \
  "${RECOVERY_STABLE_SECONDS}" \
  "${RECOVERY_MAX_SECONDS}" \
  "${SAMPLE_INTERVAL}" \
  "${BASELINE_MODE}" \
  "${RESTORE_MODE}" \
  "${FIXED_FAN_PCT}" \
  "${NORMAL_TEMP_MIN_C}" \
  "${NORMAL_TEMP_MAX_C}" \
  "${FAULT_TEMP_TARGET_C}" \
  "${BG_SIZE}" \
  "${BG_DUTY}" \
  "${BG_PERIOD_MS}" \
  "${WORKLOAD_HEADROOM_SECONDS}" > "$OUT_DIR/worker_run.log" 2>&1 <<'REMOTE'
set -euo pipefail

WORKER_REPO="$1"
RUN_ID="$2"
CC_PASSWORD="$3"
CYCLES="$4"
NORMAL_HOLD_SECONDS="$5"
FAULT_HOLD_SECONDS="$6"
RECOVERY_STABLE_SECONDS="$7"
RECOVERY_MAX_SECONDS="$8"
SAMPLE_INTERVAL="$9"
BASELINE_MODE="${10}"
RESTORE_MODE="${11}"
FIXED_FAN_PCT="${12}"
NORMAL_TEMP_MIN_C="${13}"
NORMAL_TEMP_MAX_C="${14}"
FAULT_TEMP_TARGET_C="${15}"
BG_SIZE="${16}"
BG_DUTY="${17}"
BG_PERIOD_MS="${18}"
WORKLOAD_HEADROOM_SECONDS="${19}"

cd "$WORKER_REPO"
source ../gpu-tempctl-1080ti/bin/activate
source fan_control_lab/env.sh
source "$HOME/.cargo/env"
export CCTV_DAEMON_PASSWORD="$CC_PASSWORD"
export MPLCONFIGDIR="$HOME/.config/matplotlib"
mkdir -p "$MPLCONFIGDIR"

python - "$WORKER_REPO" "$RUN_ID" "$CC_PASSWORD" "$CYCLES" "$NORMAL_HOLD_SECONDS" "$FAULT_HOLD_SECONDS" "$RECOVERY_STABLE_SECONDS" "$RECOVERY_MAX_SECONDS" "$SAMPLE_INTERVAL" "$BASELINE_MODE" "$RESTORE_MODE" "$FIXED_FAN_PCT" "$NORMAL_TEMP_MIN_C" "$NORMAL_TEMP_MAX_C" "$FAULT_TEMP_TARGET_C" "$BG_SIZE" "$BG_DUTY" "$BG_PERIOD_MS" "$WORKLOAD_HEADROOM_SECONDS" <<'PY'
import csv
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, sys.argv[1])

from fan_control_lab.gpu_supervisor_80 import read_gpu_metrics, start_workload, stop_process  # type: ignore

worker_repo = Path(sys.argv[1])
run_id = sys.argv[2]
cc_password = sys.argv[3]
cycles = int(sys.argv[4])
normal_hold_seconds = int(sys.argv[5])
fault_hold_seconds = int(sys.argv[6])
recovery_stable_seconds = int(sys.argv[7])
recovery_max_seconds = int(sys.argv[8])
sample_interval = float(sys.argv[9])
baseline_mode = sys.argv[10]
restore_mode = sys.argv[11]
fixed_fan_pct = int(float(sys.argv[12]))
normal_temp_min_c = float(sys.argv[13])
normal_temp_max_c = float(sys.argv[14])
fault_temp_target_c = float(sys.argv[15])
bg_size = int(sys.argv[16])
bg_duty = float(sys.argv[17])
bg_period_ms = int(sys.argv[18])
workload_headroom_seconds = int(sys.argv[19])

run_dir = worker_repo / "fan_control_lab" / "logs" / run_id
run_dir.mkdir(parents=True, exist_ok=False)

thermal_path = run_dir / "thermal.csv"
events_path = run_dir / "events.csv"
summary_path = run_dir / "summary.json"
report_path = run_dir / "report.txt"
meta_path = run_dir / "metadata.json"

total_budget = cycles * (normal_hold_seconds + fault_hold_seconds + recovery_max_seconds) + workload_headroom_seconds

metadata = {
    "run_id": run_id,
    "control_mode": "bgload_manual_cycle",
    "cycles": cycles,
    "normal_hold_seconds": normal_hold_seconds,
    "fault_hold_seconds": fault_hold_seconds,
    "recovery_stable_seconds": recovery_stable_seconds,
    "recovery_max_seconds": recovery_max_seconds,
    "sample_interval": sample_interval,
    "baseline_mode": baseline_mode,
    "restore_mode": restore_mode,
    "fixed_fan_pct": fixed_fan_pct,
    "normal_temp_min_c": normal_temp_min_c,
    "normal_temp_max_c": normal_temp_max_c,
    "fault_temp_target_c": fault_temp_target_c,
    "bg_size": bg_size,
    "bg_duty": bg_duty,
    "bg_period_ms": bg_period_ms,
}
meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

thermal_fieldnames = [
    "timestamp",
    "elapsed_s",
    "cycle_index",
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
event_fieldnames = ["timestamp", "elapsed_s", "cycle_index", "phase", "event", "detail"]

thermal_fp = thermal_path.open("w", newline="", encoding="utf-8")
thermal_writer = csv.DictWriter(thermal_fp, fieldnames=thermal_fieldnames)
thermal_writer.writeheader()

events_fp = events_path.open("w", newline="", encoding="utf-8")
events_writer = csv.DictWriter(events_fp, fieldnames=event_fieldnames)
events_writer.writeheader()

rows = []
start_time = time.time()
current_mode = baseline_mode


def set_mode(mode_name: str):
    subprocess.run(
        ["python", "fan_control_lab/cc.py", "-p", cc_password, "--mode", mode_name],
        cwd=worker_repo,
        check=True,
    )


def set_fixed_fan(speed_pct: int):
    subprocess.run(
        ["python", "fan_control_lab/cc.py", "-p", cc_password, "-m", "NVIDIA", "-c", "fan", "--speed", str(speed_pct)],
        cwd=worker_repo,
        check=True,
    )


def wait_for_fixed_fan(target: int, timeout: float = 20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        fan = read_gpu_metrics()["gpu_fan_pct"]
        if fan is not None and abs(fan - target) <= 3:
            return True
        time.sleep(1)
    return False


def wait_for_auto_mode(timeout: float = 20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        fan = read_gpu_metrics()["gpu_fan_pct"]
        if fan is not None and abs(fan - fixed_fan_pct) > 3:
            return True
        time.sleep(1)
    return False


def log_event(cycle_index, phase, event, detail=""):
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "elapsed_s": round(time.time() - start_time, 3),
        "cycle_index": cycle_index,
        "phase": phase,
        "event": event,
        "detail": detail,
    }
    events_writer.writerow(row)
    events_fp.flush()


def classify_state(temp: float):
    if temp < normal_temp_min_c:
        return "below_normal_band"
    if temp <= normal_temp_max_c:
        return "within_normal_band"
    if temp < fault_temp_target_c:
        return "above_normal_band"
    return "fault_target_reached"


def collect_row(cycle_index, phase, binary_label, phase_start_ts, reason, target_temp_c, stable_counter_s):
    g = read_gpu_metrics()
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "elapsed_s": round(time.time() - start_time, 3),
        "cycle_index": cycle_index,
        "phase": phase,
        "binary_label": binary_label,
        "phase_elapsed_s": round(time.time() - phase_start_ts, 3),
        "gpu_temp_c": g["gpu_temp_c"],
        "gpu_state": classify_state(g["gpu_temp_c"]) if g["gpu_temp_c"] is not None else "no_data",
        "gpu_util_pct": g["gpu_util_pct"],
        "gpu_power_w": g["gpu_power_w"],
        "gpu_fan_pct": g["gpu_fan_pct"],
        "gpu_clock_mhz": g["gpu_clock_mhz"],
        "gpu_mem_clock_mhz": g["gpu_mem_clock_mhz"],
        "current_mode": current_mode,
        "desired_mode": current_mode,
        "reason": reason,
        "infeasible": "",
        "target_temp_c": target_temp_c,
        "band_c": normal_temp_max_c - normal_temp_min_c,
        "stable_counter_s": round(stable_counter_s, 3),
    }
    rows.append(row)
    thermal_writer.writerow(row)
    thermal_fp.flush()
    return row


def summarize_phase(cycle_index, phase):
    phase_rows = [r for r in rows if r["cycle_index"] == cycle_index and r["phase"] == phase and r["gpu_temp_c"] is not None]
    if not phase_rows:
        return {"rows": 0}
    temps = [r["gpu_temp_c"] for r in phase_rows]
    fans = [r["gpu_fan_pct"] for r in phase_rows if r["gpu_fan_pct"] is not None]
    utils = [r["gpu_util_pct"] for r in phase_rows if r["gpu_util_pct"] is not None]
    clocks = [r["gpu_clock_mhz"] for r in phase_rows if r["gpu_clock_mhz"] is not None]
    powers = [r["gpu_power_w"] for r in phase_rows if r["gpu_power_w"] is not None]
    return {
        "rows": len(phase_rows),
        "temp_mean_c": round(sum(temps) / len(temps), 3),
        "temp_min_c": min(temps),
        "temp_max_c": max(temps),
        "fan_mean_pct": round(sum(fans) / len(fans), 3) if fans else None,
        "util_mean_pct": round(sum(utils) / len(utils), 3) if utils else None,
        "sm_clock_mean_mhz": round(sum(clocks) / len(clocks), 3) if clocks else None,
        "power_mean_w": round(sum(powers) / len(powers), 3) if powers else None,
    }


def print_cycle_summary(cycle_index):
    normal = summarize_phase(cycle_index, "normal_hold")
    fault = summarize_phase(cycle_index, "fault_hold")
    recovery = summarize_phase(cycle_index, "recovery_wait")
    normal_mean = normal.get("temp_mean_c")
    fault_max = fault.get("temp_max_c")
    normal_ok = bool(normal_mean is not None and normal_temp_min_c <= normal_mean <= normal_temp_max_c)
    fault_ok = bool(fault_max is not None and fault_max >= fault_temp_target_c)

    print(f"[CYCLE {cycle_index}] END")
    print(
        f"[CYCLE {cycle_index}] normal_hold "
        f"temp_mean={normal_mean}C fan_mean={normal.get('fan_mean_pct')}% "
        f"util_mean={normal.get('util_mean_pct')}% power_mean={normal.get('power_mean_w')}W"
    )
    print(
        f"[CYCLE {cycle_index}] fault_hold "
        f"temp_mean={fault.get('temp_mean_c')}C temp_max={fault_max}C "
        f"fan_mean={fault.get('fan_mean_pct')}% util_mean={fault.get('util_mean_pct')}%"
    )
    print(
        f"[CYCLE {cycle_index}] recovery_wait "
        f"temp_mean={recovery.get('temp_mean_c')}C fan_mean={recovery.get('fan_mean_pct')}% "
        f"rows={recovery.get('rows')}"
    )
    print(
        f"[CYCLE {cycle_index}] goals "
        f"normal_mean_in_band={normal_ok} fault_max_ge_target={fault_ok}"
    )


workload_proc, workload_stdout, workload_stderr = start_workload(
    run_dir,
    total_budget,
    bg_size,
    bg_duty,
    bg_period_ms,
)

try:
    set_mode(baseline_mode)
    wait_for_auto_mode()
    current_mode = baseline_mode
    log_event(0, "setup", "activate_mode", baseline_mode)

    for cycle_index in range(1, cycles + 1):
        phase = "normal_hold"
        phase_start = time.time()
        log_event(cycle_index, phase, "phase_start", f"seconds={normal_hold_seconds}")
        set_mode(baseline_mode)
        wait_for_auto_mode()
        current_mode = baseline_mode
        while time.time() - phase_start < normal_hold_seconds:
            collect_row(cycle_index, phase, "normal", phase_start, "normal_auto", normal_temp_max_c, 0.0)
            time.sleep(sample_interval)
        log_event(cycle_index, phase, "phase_end", "")

        phase = "fault_hold"
        phase_start = time.time()
        log_event(cycle_index, phase, "phase_start", f"seconds={fault_hold_seconds}")
        set_fixed_fan(fixed_fan_pct)
        wait_for_fixed_fan(fixed_fan_pct)
        current_mode = f"MANUAL_FIXED_{fixed_fan_pct}"
        while time.time() - phase_start < fault_hold_seconds:
            collect_row(cycle_index, phase, "fault", phase_start, "fault_fixed_fan", fault_temp_target_c, 0.0)
            time.sleep(sample_interval)
        log_event(cycle_index, phase, "phase_end", "")

        phase = "recovery_wait"
        phase_start = time.time()
        log_event(cycle_index, phase, "phase_start", f"stable={recovery_stable_seconds}s max={recovery_max_seconds}s")
        set_mode(baseline_mode)
        wait_for_auto_mode()
        current_mode = baseline_mode
        stable_counter_s = 0.0
        while True:
            row = collect_row(cycle_index, phase, "recovery", phase_start, "recovery_auto", normal_temp_max_c, stable_counter_s)
            temp = row["gpu_temp_c"]
            if temp is not None and normal_temp_min_c <= temp <= normal_temp_max_c:
                stable_counter_s += sample_interval
            else:
                stable_counter_s = 0.0
            if stable_counter_s >= recovery_stable_seconds:
                log_event(cycle_index, phase, "stable_recovered", f"stable_counter_s={stable_counter_s}")
                break
            if time.time() - phase_start >= recovery_max_seconds:
                log_event(cycle_index, phase, "recovery_timeout", f"stable_counter_s={stable_counter_s}")
                break
            time.sleep(sample_interval)
        log_event(cycle_index, phase, "phase_end", "")
        print_cycle_summary(cycle_index)

finally:
    stop_process(workload_proc)
    workload_stdout.close()
    workload_stderr.close()
    try:
        set_mode(restore_mode)
        log_event(0, "finalize", "restore_mode", restore_mode)
    except Exception as exc:
        log_event(0, "finalize", "restore_mode_failed", str(exc))
    thermal_fp.close()
    events_fp.close()

summary = {
    "run_id": run_id,
    "cycles": cycles,
    "goals": {
        "normal_temp_band_c": [normal_temp_min_c, normal_temp_max_c],
        "fault_temp_target_c": fault_temp_target_c,
        "fixed_fan_pct": fixed_fan_pct,
    },
    "cycles_summary": {},
}

for cycle_index in range(1, cycles + 1):
    cycle_summary = {
        "normal_hold": summarize_phase(cycle_index, "normal_hold"),
        "fault_hold": summarize_phase(cycle_index, "fault_hold"),
        "recovery_wait": summarize_phase(cycle_index, "recovery_wait"),
    }
    normal_mean = cycle_summary["normal_hold"].get("temp_mean_c")
    fault_max = cycle_summary["fault_hold"].get("temp_max_c")
    cycle_summary["goal_check"] = {
        "normal_mean_in_band": bool(normal_mean is not None and normal_temp_min_c <= normal_mean <= normal_temp_max_c),
        "fault_max_ge_target": bool(fault_max is not None and fault_max >= fault_temp_target_c),
    }
    summary["cycles_summary"][f"cycle_{cycle_index}"] = cycle_summary

summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, ensure_ascii=False))
REMOTE

mkdir -p "$OUT_DIR/worker_logs"
rsync -e "ssh ${SSH_OPTS}" -av \
  "${WORKER_SSH}:${WORKER_REPO}/fan_control_lab/logs/${RUN_ID}/" \
  "$OUT_DIR/worker_logs/"

echo "完成：$OUT_DIR"
