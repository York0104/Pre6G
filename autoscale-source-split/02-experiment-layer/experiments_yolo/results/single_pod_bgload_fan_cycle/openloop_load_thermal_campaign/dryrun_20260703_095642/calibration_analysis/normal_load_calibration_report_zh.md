# Normal-cooling open-loop calibration summary

- input_root: `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_095642`
- candidate_runs: `9`

此報告比較 offered load 與 realized service activity，但不自動選定 low/medium/high。completed RPS 只代表服務完成量，不是外部 demand。

| offered_rps | scheduled | completed | drop_ratio | timeout_rate | error_rate | latency_p95_ms | gpu_temp_p95_c | sm_clock_median_mhz | vm_age_max_s | completed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0.5 | 30.0 | 30.0 | 0.0 | 0.0 | 0.0 | 195.99929550167872 | 53.0 | 1949.0 | 0.548882246017456 | True |
| 1.0 | 60.0 | 60.0 | 0.0 | 0.0 | 0.0 | 202.15707950410433 | 60.0 | 1936.0 | 0.7325990200042725 | True |
| 1.5 | 90.0 | 90.0 | 0.0 | 0.0 | 0.0 | 201.3403169985395 | 62.0 | 1923.0 | 1.000593662261963 | True |
| 0.5 | 30.0 | 30.0 | 0.0 | 0.0 | 0.0 | 184.06820249947486 | 62.0 | 1936.0 | 0.6244950294494629 | True |
| 1.0 | 60.0 | 60.0 | 0.0 | 0.0 | 0.0 | 204.3873145012185 | 62.0 | 1923.0 | 0.9224238395690918 | True |
| 1.5 | 90.0 | 90.0 | 0.0 | 0.0 | 0.0 | 202.68766457193124 | 64.0 | 1923.0 | 0.11408209800720215 | True |
| 0.5 | 30.0 | 30.0 | 0.0 | 0.0 | 0.0 | 202.60208450781647 | 63.0 | 1923.0 | 0.7328484058380127 | True |
| 1.0 | 60.0 | 60.0 | 0.0 | 0.0 | 0.0 | 201.3311410046299 | 63.0 | 1923.0 | 1.0006470680236816 | True |
| 1.5 | 90.0 | 90.0 | 0.0 | 0.0 | 0.0 | 200.9792226497666 | 64.0 | 1923.0 | 0.2987666130065918 | True |

## 初步判讀

- 本 summary 僅代表 normal-cooling first-pass calibration，不是 replicated normal high-load baseline。
- 若所有 candidate 皆無 drop、timeout/error burst，且 GPU temperature 距 operator limit 仍有餘裕，可再規劃更多 replicate 或較細的 offered RPS 掃描。
- 不應把 completion-binned median RPS 當外部 demand；外部 demand 以 scheduled/offered RPS 為準。
