# Baseline Diagnosis Runbook

這份 runbook 用於 `Phase 1` 前的 baseline stability diagnosis。

目的：

- 驗證在無壓力情境下，`node-sentinel` 與外部 probe 是否仍出現 repeated `DOWN / DEGRADED`
- 為 `COMPUTE_LOOPS`、probe timeout、`DEGRADED` threshold 提供校正依據

## Recommended Initial Run

- duration: `20 minutes`
- target node: `icclz1`
- target host: `100.105.48.97`
- probe interval: `5s`
- compute timeout: `2000ms`
- degraded threshold: `1000ms`

## One-Command Execution

```bash
cd /home/icclz2/Pre6G/autoscale-source-split
bash 02-experiment-layer/device_availability/run_baseline_diagnosis.sh
```

若要改成 `30 minutes`：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split
DURATION_SECONDS=1800 \
bash 02-experiment-layer/device_availability/run_baseline_diagnosis.sh baseline_diagnosis_30m
```

## Outputs

輸出位於：

- `availability.csv`
- `summary.json`
- `phase_timeline.jsonl`
- `current_phase.json`

## What To Review

1. `DOWN` 是否仍持續出現
2. `sentinel_unreachable` 是否仍是主因
3. `compute_check_timeout` 是否仍出現
4. `compute_ms` 的 mean / p95 / max
5. `healthz_ms` 是否也有明顯 tail latency

## Success Criterion For Re-Entering Phase 1

在 baseline-only 診斷中，至少應先看到：

- `Node Ready=True`
- 無 repeated `DOWN`
- `compute-check` tail 穩定回到 `< 2s`

之後才建議重啟完整 quick validation。
