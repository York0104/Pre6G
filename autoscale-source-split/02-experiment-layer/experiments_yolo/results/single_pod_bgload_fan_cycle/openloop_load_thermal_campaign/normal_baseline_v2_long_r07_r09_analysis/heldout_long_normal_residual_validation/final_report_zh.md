# Held-out normal residual validation

- dataset: `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_long_r07_r09_analysis/openloop_load_conditioned_1s_dataset.csv`
- created_at_utc: `2026-07-03T14:26:38.664059+00:00`
- runs: `3`
- rows: `2700`
- folds: `6`
- split notes: `[{'split': 'leave_one_replicate_per_load_level_out', 'status': 'enabled', 'reason': 'manifest_replicate_available', 'note': 'replicate identity read from manifest_replicate column'}]`
- threshold quantile: `0.99`
- conclusion: `insufficient normal replicates; residual baseline unstable across runs`
- formal episode max composite count per held-out run: `4`

## 結論分類

- `insufficient normal replicates`
- `residual baseline unstable across runs`

這份 validation 使用 run-level holdout，不使用 random row split，也不讓同一 run 的相鄰時間點跨 train/test。threshold、residual center/scale 與 feature availability 皆只由 training normal-cooling runs 決定。
Leave-one-replicate-per-load-level split 只在 manifest 真的提供 replicate identity 時啟用；本工具不再用 run_id 排序推估 replicate。
正式結論以 debounced anomaly episodes 為主；point-wise exceedance / FA per hour 只保留為 short-run sensitivity comparison。

## Load-Level Pattern

- composite risk offered-RPS pattern: composite false alarms increase with offered_rps
- max median composite false alarms per healthy hour: `72.0`
- median target exceedance rate across held-out folds: `0.0011111111111111111`

## False Alarm Summary

| split | target | offered_rps | runs | median FA/h | median exceedance |
|---|---|---:|---:|---:|---:|
| `leave_one_replicate_per_load_level_out` | `composite_risk_score` | 0.5 | 3 | 72.000 | 0.0200 |
| `leave_one_replicate_per_load_level_out` | `gpu_temp_c` | 0.5 | 3 | 8.000 | 0.0022 |
| `leave_one_replicate_per_load_level_out` | `rolling_latency_p50` | 0.5 | 3 | 152.000 | 0.0422 |
| `leave_one_replicate_per_load_level_out` | `rolling_latency_p95` | 0.5 | 3 | 1592.000 | 0.4422 |
| `leave_one_replicate_per_load_level_out` | `sm_clock_mhz` | 0.5 | 3 | 0.000 | 0.0000 |
| `leave_one_run_out` | `composite_risk_score` | 0.5 | 3 | 72.000 | 0.0200 |
| `leave_one_run_out` | `gpu_temp_c` | 0.5 | 3 | 8.000 | 0.0022 |
| `leave_one_run_out` | `rolling_latency_p50` | 0.5 | 3 | 152.000 | 0.0422 |
| `leave_one_run_out` | `rolling_latency_p95` | 0.5 | 3 | 1592.000 | 0.4422 |
| `leave_one_run_out` | `sm_clock_mhz` | 0.5 | 3 | 0.000 | 0.0000 |

## Debounced Episode Summary

| target | offered_rps | runs | total episodes | median point exceedance sensitivity |
|---|---:|---:|---:|---:|
| `composite_risk` | 0.5 | 3 | 14 | 0.0200 |
| `gpu_temp_c` | 0.5 | 3 | 2 | 0.0022 |
| `rolling_latency_p50` | 0.5 | 3 | 8 | 0.0422 |
| `rolling_latency_p95` | 0.5 | 3 | 26 | 0.4422 |
| `sm_clock_mhz` | 0.5 | 3 | 0 | 0.0000 |

## Feature Quality

- nvidia-smi vs VM GPU util corr: `None`
- nvidia-smi vs VM GPU util median abs diff: `None`
- VM gpu_util feature present in dataset: `False`

若 feature quality issue 出現，下一步模型應避免把該 VM GPU util 欄位作為 primary feature，並以 nvidia-smi/DCGM 交叉驗證。

## Interpretation

- Observed directly: replicated normal runs 可用於 held-out false-alarm validation。
- Strong temporal/statistical evidence: normal residual threshold 必須用 held-out run 檢查，不能只看 in-sample residual。
- Inconclusive: 尚未驗證 cooling-constrained condition，也尚未證明未知根因泛化。
