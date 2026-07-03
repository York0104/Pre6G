# Replicated normal-cooling baseline summary

- input_root: `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_095642`
- runs: `9`
- offered RPS groups: `3`

| offered_rps | reps | completed | latency_p95_median | latency_p95_iqr | gpu_temp_p95_median | sm_clock_median | vm_age_max_median |
|---:|---:|---|---:|---:|---:|---:|---:|
| 0.5 | 3 | True | 195.99929550167872 | 9.266941004170803 | 62.0 | 1936.0 | 0.6244950294494629 |
| 1.0 | 3 | True | 202.15707950410433 | 1.5280867482942995 | 62.0 | 1923.0 | 0.9224238395690918 |
| 1.5 | 3 | True | 201.3403169985395 | 0.8542209610823193 | 64.0 | 1923.0 | 0.2987666130065918 |

此 replicated normal baseline 可用於下一步 normal-load residual false-alarm validation；尚未包含 cooling-constrained condition。
