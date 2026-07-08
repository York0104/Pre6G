# Phase 1 Quick Validation Attempt

Date: `2026-07-07`

Run id:

- `phase1_quick_validation_20260707_live`

## Outcome

這輪 continuous validation 未繼續跑完整個 phase ladder，而是在 `BASELINE` 階段提早中止。

中止原因不是壓力 phase 失敗，而是：

- 尚未進入 `CPU-M`
- 尚未進入 `MEM-M`
- 尚未進入 `MIX-M`
- `BASELINE` 本身已出現多筆 `DOWN` 與 `DEGRADED`

因此這輪應解讀為：

- `Phase 1 quick validation precondition failed at baseline`

## Observed Baseline Behavior

From `availability.csv`:

- total samples captured before abort: `90`
- `UP`: `64`
- `DOWN`: `18`
- `DEGRADED`: `8`

Downtime reasons:

- `sentinel_unreachable`: `12`
- `compute_check_timeout`: `5`
- `compute_check_failed`: `1`

Latency extremes observed during baseline:

- `compute_ms max`: `3853.820`
- `healthz_ms max`: `4048.032`

Representative failure samples:

- `sentinel_unreachable`
- `compute_check_timeout`
- `compute_check` tail latency `> 2s`

## Interpretation

這輪結果表示：

1. 目前 `Phase 0` short smoke evidence 仍成立。
2. 但要往 `Phase 1` 長時間連續驗證前，baseline stability 仍需先釐清。
3. 若 baseline 在無壓力下就出現 repeated `DOWN / DEGRADED`，則後續 `CPU-M / MEM-M / MIX-M` 的結果不具乾淨解釋性。

## Recommended Next Action

先不要直接重跑完整 `150m` phase ladder。

建議先做一輪 baseline-focused diagnosis：

1. 重新跑 `20-30m` baseline-only probe
2. 檢查是否存在其他背景 workload 或 node-level contention
3. 比對 `node-sentinel` 本身 `compute_check` 實際耗時與 probe-observed timeout
4. 重新校正 `COMPUTE_LOOPS`、probe timeout、或 `DEGRADED` 閾值

確認 baseline 穩定後，再重啟 `Phase 1 quick validation`。
