# Phase 1 A/B Result: Unprotected vs Pod-Level Protection

Date: `2026-07-08`

## Objective

比較單一 Worker node 設備服務可用性在以下兩種條件下的表現：

- Case A: unprotected baseline
- Case B: pod-level protection

Case B 的 protection 組合包含：

- sentinel `Guaranteed QoS`
- sentinel high `PriorityClass`
- stress jobs low `PriorityClass`

本輪仍沿用 `confirmed outage` 規則：

- `Node Ready=False` 直接計為 outage
- `healthz` 需連續 `3` 次失敗才算 confirmed outage
- 單次 `sentinel_unreachable` 記為 transient anomaly / `DEGRADED`
- 單次 `compute-check latency >= 1s` 記為 `DEGRADED`

## Compared Runs

Unprotected:

- run id: `phase1_qv_20260707_manual`
- artifacts:
  - `results/phase1_qv_20260707_manual/availability.csv`
  - `results/phase1_qv_20260707_manual/summary.json`

Protected:

- run id: `phase1_qv_20260707_protected`
- artifacts:
  - `results/phase1_qv_20260707_protected/availability.csv`
  - `results/phase1_qv_20260707_protected/summary.json`

## High-Level Summary

| Metric | Unprotected | Protected |
| --- | --- | --- |
| samples_total | `1685` | `1666` |
| DOWN | `0` | `0` |
| DEGRADED | `7` | `5` |
| confirmed_outage_events | `0` | `0` |
| sentinel_unreachable | `6` | `2` |
| compute_latency_high | `1` | `3` |

## Main Result

這輪 A/B 的核心結論是：

1. 兩個版本都沒有觀察到 confirmed outage。
2. protection 對降低 `sentinel_unreachable` 類型的瞬時異常有幫助。
3. protection 並未同步改善 `MIX-M` 與 `FINAL-RECOVERY` 階段的 tail latency。

因此，目前較精確的說法應是：

> pod-level protection 在本輪 A/B 中改善了 sentinel 可達性，但尚未證明能全面改善壓力後段的 compute latency tail。

## Phase-by-Phase Comparison

### BASELINE

Unprotected:

- `compute_mean ~= 27.677 ms`
- `compute_p95 ~= 96.062 ms`
- `compute_max ~= 277.027 ms`
- `health_max ~= 1034.168 ms`

Protected:

- `compute_mean ~= 22.540 ms`
- `compute_p95 ~= 55.439 ms`
- `compute_max ~= 199.677 ms`
- `health_max ~= 260.675 ms`

Interpretation:

- protection 版 baseline 更乾淨
- baseline 下 sentinel 可達性與 latency tail 都較穩

### CPU-M

Unprotected:

- `compute_mean ~= 19.661 ms`
- `compute_p95 ~= 59.327 ms`
- `compute_max ~= 182.576 ms`

Protected:

- `compute_mean ~= 21.223 ms`
- `compute_p95 ~= 56.605 ms`
- `compute_max ~= 169.953 ms`

Interpretation:

- 兩版都穩定
- protection 沒有明顯改變 CPU-M 主體行為

### MEM-M

Unprotected:

- `compute_mean ~= 21.431 ms`
- `compute_p95 ~= 67.953 ms`
- `compute_max ~= 292.048 ms`

Protected:

- `compute_mean ~= 23.517 ms`
- `compute_p95 ~= 82.898 ms`
- `compute_max ~= 144.717 ms`

Interpretation:

- 兩版都穩定
- protected 版 max 較低，但 p95 略高

### MIX-M

Unprotected:

- `DEGRADED = 5`
- `sentinel_unreachable = 4`
- `compute_latency_high = 1`
- `compute_mean ~= 29.353 ms`
- `compute_p95 ~= 74.100 ms`
- `compute_p99 ~= 203.472 ms`
- `compute_max ~= 1221.808 ms`

Protected:

- `DEGRADED = 2`
- `sentinel_unreachable = 2`
- `compute_latency_high = 0`
- `compute_mean ~= 53.670 ms`
- `compute_p95 ~= 298.222 ms`
- `compute_p99 ~= 597.497 ms`
- `compute_max ~= 830.874 ms`

Interpretation:

- protection 將 MIX-M 階段的 `sentinel_unreachable` 次數壓低
- 但 `compute_mean / p95 / p99` 反而變重
- 表現比較像「較少失聯，但更重的 latency tail」

### FINAL-RECOVERY

Unprotected:

- `DEGRADED = 2`
- `sentinel_unreachable = 2`
- `compute_latency_high = 0`
- `compute_mean ~= 27.151 ms`
- `compute_p95 ~= 69.266 ms`
- `compute_p99 ~= 170.609 ms`
- `compute_max ~= 307.707 ms`

Protected:

- `DEGRADED = 3`
- `sentinel_unreachable = 0`
- `compute_latency_high = 3`
- `compute_mean ~= 118.029 ms`
- `compute_p95 ~= 465.020 ms`
- `compute_p99 ~= 672.608 ms`
- `compute_max ~= 1178.985 ms`

Interpretation:

- protection 將 recovery 階段的失聯現象消除
- 但 recovery latency tail 顯著升高
- 這表示 protection 對「存活」有幫助，但對「恢復後的尾延遲」未見改善

## Sample-Level Degraded Events

Protected run degraded rows:

1. `2026-07-07T17:07:58+00:00`
   - phase: `MIX-M`
   - reason: `sentinel_unreachable`
2. `2026-07-07T17:08:11+00:00`
   - phase: `MIX-M`
   - reason: `sentinel_unreachable`
3. `2026-07-07T17:24:42+00:00`
   - phase: `FINAL-RECOVERY`
   - reason: `compute_latency_high`
   - `compute_ms ~= 1011.286`
4. `2026-07-07T17:25:48+00:00`
   - phase: `FINAL-RECOVERY`
   - reason: `compute_latency_high`
   - `compute_ms ~= 1178.985`
5. `2026-07-07T17:32:57+00:00`
   - phase: `FINAL-RECOVERY`
   - reason: `compute_latency_high`
   - `compute_ms ~= 1021.344`

## Interpretation Boundary

目前可以寫：

> 在 `Phase 1` 梯度觀測中，未保護版與 protection 版皆未觀察到 confirmed outage。protection 版降低了 `sentinel_unreachable` 類型的瞬時異常，但未同步改善混合壓力與 recovery 階段的 compute latency tail。

目前不宜直接寫：

> protection 明顯提升整體設備服務可用性與 latency 表現。

原因是：

- availability 面向的 confirmed outage 在兩版中本來都為 `0`
- protection 的收益主要集中在可達性
- tail latency 在 protected run 中沒有更好，甚至在後段 recovery 明顯較重

## Decision

基於目前 A/B 結果：

1. `Phase 1` 可視為完成。
2. 可以進入 `6h Phase 2`。
3. 進入 `Phase 2` 時，應明確標註：
   protection 目前已證明可降低失聯，但尚未證明能全面改善 latency tail。

## Recommended Phase 2 Framing

若下一步直接進 `6h Phase 2`，建議在設計與報告中明確分兩個觀察面向：

1. Availability / reachability
   - confirmed outage
   - `Node Ready`
   - `sentinel_unreachable`
2. Performance degradation
   - `compute_latency_high`
   - `compute_ms p95 / p99 / max`
   - recovery tail behavior

如此可避免把「可達性改善」與「尾延遲未改善」混成單一結論。
