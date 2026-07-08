# Baseline Diagnosis Result

Date: `2026-07-07`

Run id:

- `baseline_diagnosis_20260707_live`

## Outcome

這輪 `20-minute` baseline-only diagnosis 已完成。

結果與前一輪 aborted `Phase 1` 嘗試不同：

- 未觀察到 `DOWN`
- 僅觀察到 `1` 筆 `DEGRADED`

這表示：

- baseline 並非穩定地持續失效
- 先前 `Phase 1` baseline failure 比較像是 episodic instability，而不是每次都必然重現

## Summary

- `samples_total=219`
- `samples_down=0`
- `samples_degraded=1`
- `availability_percent=100.0%`

Latency summary:

- `compute_mean_ms=231.618`
- `compute_p95_ms=450.301`
- `compute_p99_ms=513.173`
- `compute_max_ms=1269.001`
- `health_mean_ms=48.429`
- `health_p95_ms=144.351`
- `health_p99_ms=234.358`
- `health_max_ms=1106.480`

## DEGRADED Sample

Observed `DEGRADED` row:

- timestamp: `2026-07-07T07:36:20+00:00`
- `healthz_ms=10.899`
- `compute_ms=1269.001`
- reason: none, because it remained below the `2s` `DOWN` threshold

## Interpretation

目前較合理的結論是：

1. baseline 已足以排除「每次都會立刻大量 `DOWN`」這種持續性失穩。
2. 但 baseline 仍可能出現偶發 tail latency spike。
3. `DEGRADED threshold = 1000ms` 在現況下是有辨識力的，因為它能抓到單筆異常 tail，而不會把整輪全部打成 failure。
4. `compute_timeout_ms = 2000` 暫時仍可保留。

## Recommendation

可考慮重新啟動 `Phase 1 quick validation`，但建議搭配：

1. 保留 `compute_timeout_ms=2000`
2. 保留 `degraded_threshold_ms=1000`
3. 加強記錄 background workload 狀態
4. 若再出現 baseline-only instability，再檢查是否有同時段外部背景負載
