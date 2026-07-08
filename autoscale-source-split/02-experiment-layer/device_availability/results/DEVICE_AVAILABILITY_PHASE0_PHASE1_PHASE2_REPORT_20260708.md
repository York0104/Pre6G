# Device-Service Availability Validation Report: MVP Smoke, Phase 1 A/B, and Protected Long-Run Validation

Date: `2026-07-08`

Target node:

- `icclz1`

Observer / control host:

- `icclz2`

Sentinel target:

- `http://100.105.48.97:18080`

## Scope

本報告整合單一 Worker node 設備服務可用性實驗的三個階段：

1. `Phase 0`: MVP build and short live smoke
2. `Phase 1`: quick validation and protection A/B
3. `Phase 2`: `6h` formal validation

本實驗主要檢查：

- `Node Ready`
- `node-sentinel /healthz`
- `node-sentinel /compute-check`
- 在 CPU / memory / mixed stress 下，設備服務是否仍可被探測、監控、管理

## Decision Rule

自 `Phase 1` 起，本實驗採用較務實的 `confirmed outage` 規則：

- `Node Ready=False` 直接計為 outage
- `healthz` 需連續 `3` 次失敗才算 confirmed outage
- 單次 `sentinel_unreachable` 記為 transient anomaly / `DEGRADED`
- 單次 `compute-check latency >= 1s` 記為 `DEGRADED`
- 單次 `compute_check_timeout` 或 `compute_check_failed` 視為 performance degradation，除非其形成持續 failure streak，或與 `Node Ready` 中斷同時發生

因此本報告會刻意分成兩條觀察面向：

1. Availability / reachability
2. Performance degradation / latency tail

補充：

- 文中的 `availability_percent` 均指 `confirmed_outage_availability_percent`
- 亦即只以 confirmed outage 計算，不將 transient anomaly 或 latency degradation 直接視為 outage

## Phase 0: MVP Build And Short Live Smoke

Reference:

- `results/SMOKE_COMPARISON_20260707.md`

Short smoke runs:

- `cpu_smoke_20260707_live`
- `mem_smoke_20260707_live`
- `mix_smoke_20260707_live`

Summary:

| Run | Samples | DOWN | DEGRADED | Availability |
| --- | ---: | ---: | ---: | ---: |
| `cpu_smoke` | 28 | 0 | 0 | `100.0%` |
| `mem_smoke` | 23 | 0 | 0 | `100.0%` |
| `mix_smoke` | 23 | 0 | 1 | `100.0%` |

Key observations:

1. 所有短版 smoke run 都沒有觀察到 `DOWN`。
2. `CPU-M` 與 `MEM-M` 下 `compute-check` latency 有上升，但仍遠低於 `2s`。
3. `MIX-H` 出現最重 tail，且有 `1` 筆 `DEGRADED`，峰值約 `1129.009 ms`。
4. recovery phase 都能回到低於 stress phase 的 latency 範圍。

Interpretation:

- `Phase 0` 證明 MVP 實驗鏈路可在真實 cluster 運作
- 但這仍屬短版 smoke，不是 KPI 級證據

## Phase 1: Quick Validation

### Phase 1A: Unprotected Baseline

Run:

- `phase1_qv_20260707_manual`

Summary:

| Metric | Value |
| --- | --- |
| samples_total | `1685` |
| DOWN | `0` |
| DEGRADED | `7` |
| confirmed_outage_events | `0` |
| sentinel_unreachable | `6` |
| compute_latency_high | `1` |
| availability_percent | `100.0%` |

Duration table:

| Field | Value |
| --- | --- |
| observation_start | `2026-07-07T09:08:25+00:00` |
| observation_end | `2026-07-07T11:38:24+00:00` |
| observation_duration_s | `8999.0` |
| expected_samples_at_5s | `1799.8` |
| actual_samples | `1685` |
| effective_sample_interval_s | `5.344` |

Normalized event rate per 1000 samples:

| Metric | Value |
| --- | --- |
| degraded_per_1000 | `4.154` |
| sentinel_unreachable_per_1000 | `3.561` |
| compute_latency_high_per_1000 | `0.593` |
| compute_timeout_or_failed_per_1000 | `0.000` |

Interpretation:

- 未保護版 `Phase 1` 已可視為 provisional baseline
- availability / reachability 面向沒有 confirmed outage
- `DEGRADED` 主要集中在 `MIX-M` 與 `FINAL-RECOVERY`

### Phase 1B: Protection A/B

Reference:

- `results/PHASE1_AB_PROTECTION_20260708.md`

Compared runs:

- unprotected: `phase1_qv_20260707_manual`
- protected: `phase1_qv_20260707_protected`

High-level A/B summary:

| Metric | Unprotected | Protected |
| --- | --- | --- |
| samples_total | `1685` | `1666` |
| DOWN | `0` | `0` |
| DEGRADED | `7` | `5` |
| confirmed_outage_events | `0` | `0` |
| sentinel_unreachable | `6` | `2` |
| compute_latency_high | `1` | `3` |

Normalized A/B comparison:

| Metric | Unprotected | Protected |
| --- | --- | --- |
| degraded_per_1000 | `4.154` | `3.001` |
| sentinel_unreachable_per_1000 | `3.561` | `1.200` |
| compute_latency_high_per_1000 | `0.593` | `1.801` |
| compute_timeout_or_failed_per_1000 | `0.000` | `0.000` |

Interpretation:

1. 兩個版本都沒有 observed confirmed outage。
2. 在本輪 A/B 中，protected run 觀察到較低的 `sentinel_unreachable` 次數與 rate。
3. protection 並未同步改善 `MIX-M` 與 `FINAL-RECOVERY` 的 tail latency。

Phase 1 decision:

- `Phase 1` 可視為完成
- protection 的觀察收益主要表現在可達性，而非全面 latency 改善

## Phase 2: 6h Formal Validation

Run:

- `phase2_formal_20260708_protected`

Summary:

| Metric | Value |
| --- | --- |
| samples_total | `3883` |
| DOWN | `0` |
| DEGRADED | `39` |
| confirmed_outage_events | `0` |
| sentinel_unreachable | `17` |
| compute_latency_high | `19` |
| compute_check_timeout | `2` |
| compute_check_failed | `1` |
| availability_percent | `100.0%` |

Duration table:

| Field | Value |
| --- | --- |
| observation_start | `2026-07-07T18:49:07+00:00` |
| observation_end | `2026-07-08T00:49:09+00:00` |
| observation_duration_s | `21602.0` |
| expected_samples_at_5s | `4320.4` |
| actual_samples | `3883` |
| effective_sample_interval_s | `5.565` |

Normalized event rate per 1000 samples:

| Metric | Value |
| --- | --- |
| degraded_per_1000 | `10.044` |
| sentinel_unreachable_per_1000 | `4.378` |
| compute_latency_high_per_1000 | `4.893` |
| compute_timeout_or_failed_per_1000 | `0.773` |

### Availability / Reachability View

Key findings:

1. `confirmed_outage_events = 0`
2. `max_health_failure_streak = 2`
3. `Node Ready=False` 未出現
4. `6h` 期間未觀察到 confirmed outage

Interpretation:

- 在 availability / reachability 這條口徑下，`Phase 2` 可視為通過
- `Phase 2` 雖是依 `6h` 驗證計畫執行，但正式報告應使用 timestamp 推導出的實際 observation duration，而不只由 sample count 反推

### Performance Degradation / Latency Tail View

Phase highlights:

- `BASELINE`
  - `1` 筆 transient `sentinel_unreachable`
  - `compute_max ~= 942.975 ms`
- `CPU-M`
  - `4` 筆 `DEGRADED`
  - `compute_latency_high = 3`
  - `compute_max ~= 1572.555 ms`
- `MEM-M`
  - `0` 筆 `DEGRADED`
- `MIX-H`
  - `23` 筆 `DEGRADED`
  - `sentinel_unreachable = 13`
  - `compute_latency_high = 9`
  - `compute_check_timeout = 1`
  - `compute_max ~= 2880.216 ms`
- `FINAL-RECOVERY`
  - `10` 筆 `DEGRADED`
  - `compute_latency_high = 6`
  - `sentinel_unreachable = 2`
  - `compute_check_timeout = 1`
  - `compute_check_failed = 1`
  - `compute_max ~= 2161.712 ms`

Interpretation:

- `MIX-H` 是主要退化來源
- `FINAL-RECOVERY` 顯示壓力解除後，latency tail 並未立刻回穩
- 因此 `Phase 2` 雖在 availability 面向成立，但 performance degradation 仍明顯存在

## Consolidated Conclusion

截至 `2026-07-08`，本實驗已完成單一 Worker node 設備服務可用性之三階段驗證。

1. `Phase 0` 證明 `node-sentinel`、外部 probe、stress runner 與結果紀錄鏈路可在真實 K3s cluster 中運作。
2. `Phase 1` 完成未保護 baseline 與 pod-level protection A/B；兩組皆未觀察到 confirmed outage，且 protected run 觀察到較少的 transient `sentinel_unreachable` 事件。
3. `Phase 2` 進一步於 protected 條件下完成長時間驗證；在 confirmed-outage availability 定義下，觀測期間未出現 `Node Ready` interruption 或 confirmed sentinel outage。
4. 然而，本實驗同時觀察到 mixed stress 與 final recovery 階段存在明顯 compute latency tail。
5. 因此目前結果應解讀為：設備服務可達性在本輪測試條件下成立，但效能退化與恢復尾延遲仍需作為獨立 SLI 持續追蹤。

## What Can Be Claimed

目前可以寫：

> 在單一 Worker node 條件下，本研究完成了從 MVP smoke、Phase 1 quick validation / protection A/B，到 protected long-run Phase 2 validation 的設備服務可用性實驗。依 confirmed-outage 規則，本輪 Phase 2 觀測期間未出現 confirmed outage，目標節點維持 Node Ready，且 `node-sentinel` 未形成連續失聯事件。Pod-level protection 在 Phase 1 A/B 中觀察到較少的 transient `sentinel_unreachable`，但未同步改善 mixed stress 與 recovery 階段的 compute latency tail。

## What Should Not Yet Be Claimed

目前不宜直接寫：

> protection 明顯提升整體設備服務可用性與 latency 表現。

也不宜直接寫：

> 已全面驗證單節點設備服務 `>=99.9%` 且效能穩定達標。

也不宜直接寫：

> 已全面驗證單節點設備服務長期滿足 `99.9%` SLA。

原因是：

- unprotected 與 protected 兩組在 confirmed outage 上皆為 `0`
- protection 的主要觀察收益是 transient `sentinel_unreachable` 次數下降，而不是 confirmed outage reduction
- confirmed outage 雖為 `0`，但 `DEGRADED` 與 latency tail 仍在 `MIX-H` / `FINAL-RECOVERY` 顯著存在
- 本輪結果僅涵蓋單一 target node、特定 stress profile、特定 protection 設定與有限觀測時間
- 若要形成 KPI 驗收等級證據，仍需補充更完整的 downtime 定義、長時間重複 run，以及跨壓力強度或跨節點驗證

## Suggested Next Step

後續若要繼續深化，可優先選一條：

1. latency-tail 收斂
   - 針對 `MIX-H` 與 `FINAL-RECOVERY` 再做 focused rerun
   - 校正 stress 強度或探測參數
2. KPI formalization
   - 將 confirmed outage、transient anomaly、performance degradation 分開列為獨立指標
   - 明確定義論文/報告中對 availability 與 degradation 的主張邊界
