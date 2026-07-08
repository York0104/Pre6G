# Device Availability MVP Progress

Last updated: `2026-07-07`

## Goal

建立單一 Worker node 的設備服務可用性實驗，分階段完成：

- `Phase 0`: MVP build and live smoke validation
- `Phase 1`: quick availability validation
- `Phase 2`: formal KPI validation

## Phase Status

| Phase | Status | Scope |
| --- | --- | --- |
| `Phase 0: MVP Build and Live Smoke` | done | Sentinel、direct probe、CSV/summary、`CPU-M / MEM-M / MIX-H` short smoke |
| `Phase 1: Quick Availability Validation` | in progress | `2h` 連續觀測，含 baseline / stress / recovery |
| `Phase 2: Formal KPI Validation` | later | `6h` 或 `24h`，含 downtime / degraded / KPI 證據 |

## Implementation Status

| Item | Status | Notes |
| --- | --- | --- |
| Architecture design doc | done | `README.md` 已落地 |
| Progress tracker | done | 本文件 |
| `node-sentinel` minimal service | done | 使用 Python stdlib HTTP server，無額外套件依賴 |
| Sentinel manifest | done | `DaemonSet` 初版已建立，MVP 版不使用 `system-node-critical` |
| CPU stress manifest | done | Job 範本已建立 |
| Memory stress manifest | done | Job 範本已建立 |
| Availability probe | done | 可定時寫 `availability.csv` 與 `summary.json`，MVP 不以 metrics 失敗判 `DOWN` |
| Stress runner skeleton | done | 6 小時 phase orchestration 初版 |
| Real cluster smoke test | done | `2026-07-07` 已在 `icclz1` 實際部署 sentinel 並完成 5 次 probe smoke |
| Short CPU stress smoke test | done | `2026-07-07` 已完成 `BASELINE -> CPU-M -> RECOVERY-1` phase-aware live run |
| Short MEM-M stress smoke test | done | `2026-07-07` 已完成 `BASELINE -> MEM-M -> RECOVERY-1` phase-aware live run |
| Short MIX-H stress smoke test | done | `2026-07-07` 已完成 `BASELINE -> MIX-H -> RECOVERY-1` phase-aware live run |
| Smoke comparison summary | done | 已整理 `CPU-M / MEM-M / MIX-H` 三組 `compute_ms` 對照 |
| Phase 1 quick-validation helper | done | 已補 `phase1_quick_validation` profile、one-command script 與 runbook |
| Phase 1 quick-validation live attempt | done | `2026-07-07` 已實際啟動，但在 `BASELINE` 階段因 repeated `DOWN / DEGRADED` 提前中止 |
| Baseline-diagnosis helper | done | 已補 baseline-only script、runbook 與 probe degraded-threshold 參數 |
| Baseline-diagnosis live run | done | `2026-07-07` 已完成 `20m` baseline-only diagnosis，結果為 `0 DOWN / 1 DEGRADED` |
| Phase 1 quick-validation rerun | done | `2026-07-07` rerun 仍在 baseline 後段與 `CPU-M` 出現 repeated instability，已提前中止 |
| Mild CPU validation helper | done | 已補保守版 `baseline + mild CPU` 腳本與 runbook |
| Background-worker sentinel refactor | done | `/compute-check` 改讀背景 worker 最近結果，不再在 request 當下同步重算 |
| D1-D4 diagnosis tooling | done | 已補 observer/local probe loops、case runner 與 runbook |
| Short D3/D4 live diagnosis | done | `2026-07-07` 已完成背景 worker 版短版 `D3/D4`，observer 與 localhost probes 均穩定 |
| Threshold calibration | pending | `compute-check` loops / mem bytes 需依現場校正 |
| Result summarization refinement | pending | phase breakdown 與 richer downtime analytics 可再補 |

## Current Risks

1. `node-sentinel` manifest 已改為依賴 `ConfigMap` 掛載腳本，部署前需先建立 `node-sentinel-script`。
2. `polinux/stress:latest` 已於 `icclz1` 完成首次拉取並成功執行；後續正式測試前應確認 image 已預拉取或 registry 可用，以避免 image pull latency 干擾 phase。
3. `metrics-url` 預設先用 `node-exporter`，若現場主要依賴 Netdata，可在 probe 參數中切換。
4. MVP 版故意不把 metrics reachability 納入 `DOWN`，因此若要主張整體監控鏈 availability，需第二輪再擴充判定。
5. `icclz1` 實測對 `harbor.iccl.local:8088` 存在 `connection refused`，因此 sentinel 目前改回 `python:3.12-slim`。

## Current Interpretation

目前結果可寫為：

> 已完成單一 Worker node 設備服務可用性 MVP 的 live smoke test。於 CPU、記憶體及混合資源壓力下，目標節點維持 Kubernetes Ready 狀態，`node-sentinel` 持續回應 health 與 compute check，未觀察到服務中斷事件；惟在混合壓力下已觀察到單筆 compute-check tail latency 上升，後續將用於校正壓力強度與服務退化門檻。

目前結果不應直接寫為：

> 已驗證設備服務可用性 `>= 99.9%`

原因是目前僅完成短版 smoke run，尚非 `2h`、`6h` 或 `24h` KPI 證據。

補充：

- 首輪 `Phase 1 quick validation` 嘗試已在 `BASELINE` 階段觀察到 repeated `DOWN / DEGRADED`，但依較務實的 `confirmed outage` 定義，單次 probe 異常不應直接視為設備服務中斷。
- `mild_cpu_validation_20260707_live` 回放後，`max health-failure streak=2`、`confirmed outage events=0`、`node_not_ready=0`，因此較接近「有 transient anomaly，但無 confirmed outage」。
- `2026-07-07` 已將 `node-sentinel` 切成 background worker 架構，並完成短版 `D3/D4` live diagnosis；目前短版 baseline 與 mild CPU 觀察皆未再看到 observer/local 路徑失穩。

## Latest Smoke Test

Date:

- `2026-07-07`

Cluster actions:

- labeled node `icclz1` with `availability-test=target`
- created ConfigMap `node-sentinel-script` in `intent-lab`
- deployed `node-sentinel` DaemonSet to `icclz1`

Observed target host:

- `100.105.48.97:18080`

Direct endpoint check:

- `/healthz` returned `200`
- `/compute-check` returned `200`
- first direct `compute-check` observed around `517 ms`

Probe smoke result:

- output dir: `02-experiment-layer/device_availability/results/smoke_20260707_live`
- samples: `5`
- `UP`: `5`
- `DOWN`: `0`
- reported availability: `100.0%`
- probe-observed `compute_ms`: approximately `66 ms` to `484 ms`

Notes:

- this smoke run used direct probe only; no stress phase was active, so `phase=unknown`
- `metrics_ok` remained `1` in the smoke run, but MVP state classification still ignores metrics failures

## Latest CPU Stress Smoke Test

Date:

- `2026-07-07`

Profile:

- `BASELINE 30s`
- `CPU-M 60s`
- `RECOVERY-1 30s`

Artifacts:

- `02-experiment-layer/device_availability/results/cpu_smoke_20260707_live/availability.csv`
- `02-experiment-layer/device_availability/results/cpu_smoke_20260707_live/summary.json`
- `02-experiment-layer/device_availability/results/cpu_smoke_20260707_live/phase_timeline.jsonl`

Observed results:

- `samples_total=28`
- `samples_down=0`
- `availability_percent=100.0`
- `CPU-M` phase under live stress still remained `UP`
- probe-observed `compute_ms` during `CPU-M` stayed below the `2s` threshold

Operational findings:

1. `polinux/stress:latest` is usable on `icclz1` after first pull completes.
2. Original stress manifests were missing `command: ["stress"]`; this has been fixed.
3. Fixed-iteration probe continued sampling a few `COMPLETE` rows after the phase timeline ended; probe now supports `--stop-phase-name COMPLETE` for cleaner future runs.

## Latest MEM-M And MIX-H Smoke Tests

Artifacts:

- `02-experiment-layer/device_availability/results/mem_smoke_20260707_live/`
- `02-experiment-layer/device_availability/results/mix_smoke_20260707_live/`
- `02-experiment-layer/device_availability/results/SMOKE_COMPARISON_20260707.md`

Observed results:

- `mem_smoke`: `samples_total=23`, `DOWN=0`, `DEGRADED=0`, `availability=100.0%`
- `mix_smoke`: `samples_total=23`, `DOWN=0`, `DEGRADED=1`, `availability=100.0%`
- `mix_smoke` recorded one heavier-tail `compute_ms` sample above `1s`, but still below the `2s` `DOWN` threshold

## Next Steps

1. 以新規則重跑 `Phase 1 quick validation`：
   `Node Ready=False` 直接算 outage；`healthz` 需連續 `3` 次失敗才算 confirmed outage；單次 `compute timeout` 先記為 `DEGRADED`。
2. 保留 `D1-D4` 旁證欄位，確認 observer 與 localhost 結果一致。
3. 若完整 `2h` 版仍出現連續 `healthz` failure，再回頭追 Pod / network / kubelet 事件。
4. `2h` 版穩定後，再規劃 `6h` 或 `24h` 正式 KPI 驗證。

## Recommended Next Run

下一輪不建議直接再次重跑完整 quick-validation ladder。

建議先做較保守驗證，例如：

```text
00:00-00:20  BASELINE
00:20-00:40  CPU-M (milder)
00:40-00:50  RECOVERY
```

若這輪穩定，再回到完整 ladder：

```text
00:00-00:20  BASELINE
00:20-00:50  CPU-M
00:50-01:00  RECOVERY-1
01:00-01:30  MEM-M
01:30-01:40  RECOVERY-2
01:40-02:10  MIX-M
02:10-02:30  FINAL-RECOVERY
```

這一輪先觀察四件事：

1. `Node Ready` 是否持續為 `True`
2. `healthz` 是否持續成功
3. `compute-check` 是否持續 `< 2s`
4. `MIX-M` 是否持續出現 `> 1s` tail latency

## Latest Phase 1 Attempt

Artifacts:

- `02-experiment-layer/device_availability/results/phase1_quick_validation_20260707_live/availability.csv`
- `02-experiment-layer/device_availability/results/PHASE1_QUICK_VALIDATION_ATTEMPT_20260707.md`

Observed outcome:

- run aborted during `BASELINE`
- `samples_total=90`
- `UP=64`
- `DOWN=18`
- `DEGRADED=8`
- dominant failure reasons were `sentinel_unreachable` and `compute_check_timeout`

## Latest Baseline Diagnosis

Artifacts:

- `02-experiment-layer/device_availability/results/baseline_diagnosis_20260707_live/availability.csv`
- `02-experiment-layer/device_availability/results/BASELINE_DIAGNOSIS_20260707.md`

Observed outcome:

- `samples_total=219`
- `DOWN=0`
- `DEGRADED=1`
- `compute_p95_ms=450.301`
- `compute_p99_ms=513.173`
- single degraded sample observed at `compute_ms=1269.001`

## Latest Phase 1 Rerun

Artifacts:

- `02-experiment-layer/device_availability/results/phase1_quick_validation_20260707_rerun/availability.csv`
- `02-experiment-layer/device_availability/results/PHASE1_QUICK_VALIDATION_RERUN_20260707.md`

Observed outcome:

- `samples_total=202`
- `UP=181`
- `DOWN=14`
- `DEGRADED=7`
- baseline 後段與 `CPU-M` 均觀察到 instability
- dominant issue remained `sentinel_unreachable`
