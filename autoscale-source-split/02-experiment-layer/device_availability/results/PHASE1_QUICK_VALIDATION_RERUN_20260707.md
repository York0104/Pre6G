# Phase 1 Quick Validation Rerun

Date: `2026-07-07`

Run id:

- `phase1_quick_validation_20260707_rerun`

## Outcome

在 baseline-only diagnosis 顯示 `0 DOWN / 1 DEGRADED` 後，重新啟動 `Phase 1 quick validation`。

這輪 rerun 仍未能安全進入完整 quick-validation 流程，原因是：

- baseline 前半段一度穩定
- baseline 後半段重新出現 repeated `sentinel_unreachable`
- 進入 `CPU-M` 後又出現 `compute_check_timeout` 與更多 `sentinel_unreachable`

因此這輪應解讀為：

- `Phase 1 quick validation rerun failed`
- 問題不是單純 phase orchestration，而是 `node-sentinel / probe path` 在較長時間或 CPU contention 下仍不夠穩定

## Summary

- `samples_total=202`
- `UP=181`
- `DOWN=14`
- `DEGRADED=7`

Downtime reasons:

- `sentinel_unreachable=12`
- `compute_check_failed=1`
- `compute_check_timeout=1`

Latency summary:

- `BASELINE compute mean ms=308.747`
- `BASELINE compute max ms=3252.517`
- `CPU-M compute mean ms=2223.214`
- `CPU-M compute max ms=4738.210`

## Key Observation

baseline-only diagnosis 並未穩定重現 failure，但 rerun 中：

1. baseline 後半段仍可出現多筆 `sentinel_unreachable`
2. `CPU-M` 會進一步放大 `compute-check` tail
3. 單靠目前 `node-sentinel` 實作與參數，尚不足以支撐連續 quick validation

## Recommended Next Action

先不要直接再重跑整輪 `Phase 1`。

建議優先處理：

1. 降低 `node_sentinel.py` 的 `COMPUTE_LOOPS`
2. 重新檢查 probe `http timeout` 與 `compute_timeout_ms`
3. 釐清 `sentinel_unreachable` 是否來自 server thread starvation、network stall，或 probe timeout 太緊
4. 先做一輪較保守的 baseline + mild CPU validation，再決定是否重新進完整 phase ladder
