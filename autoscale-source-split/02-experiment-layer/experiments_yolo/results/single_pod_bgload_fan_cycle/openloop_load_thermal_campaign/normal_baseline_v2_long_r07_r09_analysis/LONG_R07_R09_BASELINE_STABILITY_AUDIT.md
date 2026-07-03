# Long r07-r09 Normal-Cooling Baseline Stability Audit

## Scope

This audit combines three normal-cooling long v2 runs. No fan control, CoolerControl, Kubernetes control, cooling-constrained pilot, or GPU stress was executed.

## Runs

| replicate | run_id | measurement rows | latency p50 first-last delta ms | latency p95 first-last delta ms | GPU temp delta C | SM clock delta MHz | after-120s p50 ms | after-120s p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| r07_long | r07_long_normal_smoke_20260703_211041 | 900 | -4.460 | 0.664 | 0.000 | 0.000 | 187.295 | 204.903 |
| r08_long | r08_long_normal_smoke_20260703_214750 | 900 | 1.381 | 2.905 | 0.000 | 0.000 | 202.394 | 209.983 |
| r09_long | r09_long_normal_smoke_20260703_220649 | 900 | 0.199 | 2.637 | 0.000 | 0.000 | 185.515 | 195.829 |

## Aggregate

| metric | median | min | max | std |
|---|---:|---:|---:|---:|
| after_120s_latency_p50_p50 | 187.295 | 185.515 | 202.394 | 9.274 |
| after_120s_latency_p95_p50 | 204.903 | 195.829 | 209.983 | 7.170 |
| latency_p50_first_to_last_delta_ms | 0.199 | -4.460 | 1.381 | 3.088 |
| latency_p95_first_to_last_delta_ms | 2.637 | 0.664 | 2.905 | 1.224 |
| gpu_temp_first_to_last_delta_c | 0.000 | 0.000 | 0.000 | 0.000 |
| sm_clock_first_to_last_delta_mhz | 0.000 | 0.000 | 0.000 | 0.000 |

## Interpretation

The long normal-cooling protocol is cleaner than the 300s short replicates for estimating a latency baseline after service-state stabilization. However, the after-120s latency p50/p95 levels still differ across runs, so this should be treated as a stronger normal baseline dataset rather than final proof of deployable residual thresholds. Cooling-constrained pilot should remain gated on a matched design and a pre-registered stability criterion.

## Held-Out And Service-State Normalized Validation

A held-out residual validation over r07-r09 still reports unstable raw latency thresholds across runs: r08 is treated as an all-run rolling_latency_p50 anomaly because its normal latency level is higher than r07/r09. This is a normal run-level service baseline shift, not thermal degradation evidence.

After applying a 180s run-local healthy calibration window and excluding that window from formal scoring:

- rolling_latency_p50 episodes: `0`
- rolling_latency_p95 episodes: `0`
- composite risk episodes remain small and are not latency-driven: total `10`, max per held-out run `3`

Interpretation: the long normal protocol plus run-local healthy calibration is a much more defensible baseline for future matched cooling-constrained pilot design. Raw cross-run latency residual without calibration is still too sensitive to service-state baseline shifts.
