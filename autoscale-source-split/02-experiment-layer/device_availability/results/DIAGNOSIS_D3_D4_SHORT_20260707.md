# D3/D4 Short Diagnosis After Background-Worker Refactor

Date: `2026-07-07`

## Purpose

驗證 `node-sentinel` 改為 background compute worker 後：

- `/healthz` 與 `/compute-check` 是否已不再彼此阻塞
- observer 與 worker localhost 觀測是否一致
- mild CPU 下是否仍可穩定探測

## D3 Short Rerun

Run id:

- `d3_bgworker_20260707_short_rerun`

Observed result:

- `observer_healthz`: `12/12` HTTP `200`
- `observer_compute`: `12/12` HTTP `200`
- `local_healthz`: `12/12` HTTP `200`
- `local_compute`: `12/12` HTTP `200`
- sentinel Pod restart: `0`

Latency snapshot:

- observer `healthz max ~= 137.742 ms`
- observer `compute max ~= 139.141 ms`
- localhost `healthz max ~= 202.076 ms`
- localhost `compute max ~= 183.612 ms`

Interpretation:

- background worker 架構下，baseline 診斷路徑已穩定
- 先前短版 D3 初跑的 observer `compute` 異常，已確認是 observer 腳本共用暫存檔造成的 race，而非 sentinel 本身失效

## D4 Short Run

Run id:

- `d4_bgworker_20260707_short`

Observed result:

- `observer_healthz`: `12/12` HTTP `200`
- `observer_compute`: `12/12` HTTP `200`
- `local_healthz`: `12/12` HTTP `200`
- `local_compute`: `12/12` HTTP `200`
- sentinel Pod restart: `0`

Latency snapshot:

- observer `healthz p95 ~= 64.940 ms`, `max ~= 83.976 ms`
- observer `compute p95 ~= 33.878 ms`, `max ~= 54.390 ms`
- localhost `healthz p95 ~= 0.796 ms`, `max ~= 198.412 ms`
- localhost `compute p95 ~= 0.761 ms`, `max ~= 92.492 ms`

Interpretation:

- mild CPU 下未觀察到 confirmed outage
- `/healthz` 與 `/compute-check` 在 observer / localhost 兩側皆持續可達
- 短版結果支持下一步回到 `2h Phase 1 quick validation`

## Conclusion

截至 `2026-07-07`：

- `node-sentinel` 同步 compute 架構已不再是主要阻塞點
- 短版 baseline 與 mild CPU 旁證皆支持以較務實的 `confirmed outage` 規則重啟 `Phase 1`
- 目前不應直接宣稱 `>=99.9%`，但可以說明：
  背景 worker 版 sentinel 已通過短版診斷，具備進入 `2h` quick validation 的條件
