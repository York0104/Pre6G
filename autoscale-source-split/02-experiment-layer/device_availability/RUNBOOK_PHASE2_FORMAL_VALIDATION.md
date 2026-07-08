# Phase 2 Formal Validation Runbook

這份 runbook 對應 `Phase 2: Formal KPI Validation`。

## Objective

在已完成 `Phase 1` 與 protection A/B 後，執行 `6h` 長版觀測，累積：

- availability / reachability 證據
- degradation / latency tail 證據

## Observation Dimensions

Phase 2 建議分成兩條觀察口徑：

1. Availability / reachability
   - `confirmed_outage_events`
   - `Node Ready`
   - `sentinel_unreachable`
2. Performance degradation
   - `compute_latency_high`
   - `compute_ms p95 / p99 / max`
   - recovery tail behavior

## 6h Phase Table

```text
00:00-00:30  BASELINE
00:30-01:30  CPU-M
01:30-02:00  RECOVERY-1
02:00-03:00  MEM-M
03:00-03:30  RECOVERY-2
03:30-05:00  MIX-H
05:00-06:00  FINAL-RECOVERY
```

## Recommended Run ID

Protected:

- `phase2_formal_20260708_protected`

Unprotected:

- `phase2_formal_20260708_unprotected`

## Protected Execution

Precondition:

- sentinel 已套用 protection overlay
- overlay 預建 stress jobs 已清理

Command:

```bash
cd /home/icclz2/Pre6G/autoscale-source-split

STRESS_PRIORITY_CLASS=device-availability-stress-low \
CPU_STRESS_REQUEST_CPU=500m \
CPU_STRESS_LIMIT_CPU=4 \
CPU_STRESS_REQUEST_MEMORY=64Mi \
CPU_STRESS_LIMIT_MEMORY=128Mi \
MEM_STRESS_REQUEST_CPU=250m \
MEM_STRESS_LIMIT_CPU=1 \
MEM_STRESS_REQUEST_MEMORY=256Mi \
MEM_STRESS_LIMIT_MEMORY=7Gi \
OUT_DIR=02-experiment-layer/device_availability/results/phase2_formal_20260708_protected \
bash 02-experiment-layer/device_availability/run_phase2_formal_validation.sh phase2_formal_20260708_protected
```

## Output Artifacts

- `availability.csv`
- `summary.json`
- `phase_timeline.jsonl`
- `current_phase.json`
- `probe.log`

## Decision Rule

若 `confirmed_outage_events = 0`，可說明：

- 在本輪 `6h` 觀測中未觀察到 confirmed outage

若仍出現 `compute_latency_high`，應單獨統計，不要與 outage 混寫。
