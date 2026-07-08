# Phase 2 Protected Baseline Summary

Status: `sealed baseline`

Run id:

- `phase2_formal_20260708_protected`

Role:

- `P2 Pod-level protected baseline`
- 後續 `Node-level protection` round 的對照基線

## Observation Window

| Field | Value |
| --- | --- |
| start_time | `2026-07-07T18:49:07+00:00` |
| end_time | `2026-07-08T00:49:09+00:00` |
| actual_observation_duration_s | `21602.0` |
| expected_samples_at_5s | `4320.4` |
| actual_samples | `3883` |
| effective_sample_interval_s | `5.565` |

## Outcome Summary

| Metric | Value |
| --- | --- |
| confirmed_outage_events | `0` |
| confirmed_outage_availability_percent | `100.0%` |
| DEGRADED count | `39` |
| DEGRADED rate per 1000 | `10.044` |
| sentinel_unreachable rate per 1000 | `4.378` |
| compute_latency_high rate per 1000 | `4.893` |
| compute_timeout_or_failed rate per 1000 | `0.773` |

## Interpretation

1. 在 `confirmed outage` 規則下，本輪 `6h` 觀測未出現 confirmed outage。
2. 這份 baseline 支持後續將 `availability / reachability` 與 `performance degradation / latency tail` 分開比較。
3. 後續若導入 `pod-memory-limit`、`evictionHard`、`systemReserved / kubeReserved`，都應以這份結果作為 protected baseline 對照。

## Known Limitations

1. `availability_percent` 僅反映 confirmed outage，不代表零異常樣本。
2. `MIX-H` 與 `FINAL-RECOVERY` 仍有明顯 latency tail，不能解讀為效能全面穩定。
3. 本輪只涵蓋單一 target node、單一 protection 組合、單次 `6h` 觀測。
