# Mild CPU Validation Runbook

這份 runbook 用於 `Phase 1` 前的保守驗證。

目的：

- 在較低 compute-check 負載下重新驗證 `baseline + mild CPU`
- 保持 `compute_timeout_ms=2000` 與 `degraded_threshold_ms=1000`
- 確認 `sentinel_unreachable` 是否下降

## Validation Ladder

```text
00:00-00:20  BASELINE
00:20-00:40  CPU-M (mild)
00:40-00:50  RECOVERY-1
```

## Settings

- `NODE_SENTINEL_COMPUTE_LOOPS=8000`
- `CPU_M_WORKERS=2`
- `compute_timeout_ms=2000`
- `degraded_threshold_ms=1000`

## One-Command Execution

```bash
cd /home/icclz2/Pre6G/autoscale-source-split
bash 02-experiment-layer/device_availability/run_mild_cpu_validation.sh
```

## Success Signal

至少希望看到：

1. `DOWN=0`
2. `sentinel_unreachable=0`
3. `CPU-M` 期間仍維持 `compute-check < 2s`
4. recovery phase 明顯回落
