#!/usr/bin/env bash
set -euo pipefail

BATCH_ID="${1:-batch_$(date +%Y%m%d_%H%M%S)}"

AUTOSCALE_DIR="${AUTOSCALE_DIR:-$HOME/AutoScale}"
BASE_OUT_DIR="${BASE_OUT_DIR:-$HOME/exp_runs/$BATCH_ID}"

CYCLES="${CYCLES:-6}"
TARGET="${TARGET:-90}"
BAND="${BAND:-3}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-600}"

SUMMARY_PY="${AUTOSCALE_DIR}/experiments/thermal_analysis/summarize_multi_cycle.py"

mkdir -p "$BASE_OUT_DIR"

MANIFEST="$BASE_OUT_DIR/batch_manifest.csv"
echo "cycle_idx,run_id,run_dir,target,band,start_time,end_time,duration_sec,status" > "$MANIFEST"

BATCH_START_EPOCH=$(date +%s)

ok_count=0
fail_count=0
last_status="ok"

print_header() {
  echo "============================================================"
  echo "BATCH_ID=$BATCH_ID"
  echo "BASE_OUT_DIR=$BASE_OUT_DIR"
  echo "CYCLES=$CYCLES"
  echo "TARGET=$TARGET"
  echo "BAND=$BAND"
  echo "COOLDOWN_SECONDS=$COOLDOWN_SECONDS"
  echo "START_TIME=$(date -Iseconds)"
  echo "============================================================"
  echo
}

print_cycle_banner() {
  local i="$1"
  local run_id="$2"
  local run_dir="$3"
  local start_time="$4"

  echo "------------------------------------------------------------"
  echo "[Cycle $i/$CYCLES] START"
  echo "RUN_ID=$run_id"
  echo "RUN_DIR=$run_dir"
  echo "START=$start_time"
  echo "Progress(before run): ok=$ok_count fail=$fail_count"
  echo "------------------------------------------------------------"
}

cooldown_wait() {
  local total="$1"
  local remain="$total"

  if [[ "$total" -le 0 ]]; then
    return 0
  fi

  echo
  echo "==> cooldown start: ${total}s"
  while [[ "$remain" -gt 0 ]]; do
    if [[ "$remain" -ge 60 ]]; then
      echo "    cooldown remaining: ${remain}s"
      sleep 60
      remain=$((remain - 60))
    else
      echo "    cooldown remaining: ${remain}s"
      sleep "$remain"
      remain=0
    fi
  done
  echo "==> cooldown done"
  echo
}

run_final_summary() {
  local summary_csv="$BASE_OUT_DIR/batch_summary.csv"

  echo
  echo "==================== BATCH FINAL SUMMARY ===================="
  echo "Batch dir: $BASE_OUT_DIR"
  echo "Manifest : $MANIFEST"

  if [[ -f "$SUMMARY_PY" ]]; then
    python "$SUMMARY_PY" \
      --batch-dir "$BASE_OUT_DIR" \
      --out "$summary_csv"
  else
    echo "找不到 summarize_multi_cycle.py，略過 batch_summary 生成"
    return 0
  fi

  echo
  echo "-------------------- manifest tail -------------------------"
  tail -n 10 "$MANIFEST" || true

  echo
  if [[ -f "$summary_csv" ]]; then
    echo "-------------------- batch_summary head --------------------"
    head -n 10 "$summary_csv" || true
  fi

  local total_done
  total_done=$((ok_count + fail_count))
  local batch_end_epoch
  batch_end_epoch=$(date +%s)
  local batch_duration
  batch_duration=$((batch_end_epoch - BATCH_START_EPOCH))

  echo
  echo "-------------------- overall stats -------------------------"
  echo "total_cycles_requested=$CYCLES"
  echo "total_cycles_finished=$total_done"
  echo "ok_count=$ok_count"
  echo "fail_count=$fail_count"
  echo "last_status=$last_status"
  echo "batch_duration_sec=$batch_duration"
  echo "============================================================"
}

print_header

for i in $(seq 1 "$CYCLES"); do
  RUN_ID=$(printf "%s_c%03d" "$BATCH_ID" "$i")
  RUN_DIR="$BASE_OUT_DIR/$RUN_ID"
  START_TIME=$(date -Iseconds)
  START_EPOCH=$(date +%s)

  mkdir -p "$RUN_DIR"
  print_cycle_banner "$i" "$RUN_ID" "$RUN_DIR" "$START_TIME"

  set +e
  RUN_DIR="$RUN_DIR" TARGET="$TARGET" BAND="$BAND" \
    bash "$AUTOSCALE_DIR/experiments/thermal_analysis/run_yolo26_workload_experiment.sh" "$RUN_ID"
  RC=$?
  set -e

  END_TIME=$(date -Iseconds)
  END_EPOCH=$(date +%s)
  DURATION_SEC=$((END_EPOCH - START_EPOCH))

  if [[ $RC -eq 0 ]]; then
    STATUS="ok"
    ok_count=$((ok_count + 1))
  else
    STATUS="fail"
    fail_count=$((fail_count + 1))
  fi
  last_status="$STATUS"

  echo "$i,$RUN_ID,$RUN_DIR,$TARGET,$BAND,$START_TIME,$END_TIME,$DURATION_SEC,$STATUS" >> "$MANIFEST"

  echo
  echo "[Cycle $i/$CYCLES] END"
  echo "STATUS=$STATUS"
  echo "END=$END_TIME"
  echo "DURATION_SEC=$DURATION_SEC"
  echo "Progress(after run): ok=$ok_count fail=$fail_count"
  echo

  if [[ "$STATUS" != "ok" ]]; then
    echo "cycle failed: $RUN_ID"
    break
  fi

  if [[ "$i" -lt "$CYCLES" ]]; then
    cooldown_wait "$COOLDOWN_SECONDS"
  fi
done

run_final_summary
