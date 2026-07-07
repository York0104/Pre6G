# Device Availability MVP Progress

Last updated: `2026-07-07`

## Goal

建立單一 Worker node 的設備服務可用性實驗 MVP，包含：

- `node-sentinel`
- `availability_probe.py`
- `stress_runner.sh`
- Kubernetes manifests
- operator-facing 設計與追蹤文件

## Status

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
| Threshold calibration | pending | `compute-check` loops / mem bytes 需依現場校正 |
| Result summarization refinement | pending | phase breakdown 與 richer downtime analytics 可再補 |

## Current Risks

1. `node-sentinel` manifest 已改為依賴 `ConfigMap` 掛載腳本，部署前需先建立 `node-sentinel-script`。
2. `polinux/stress:latest` 是否已存在於現場可拉取路徑，尚未驗證。
3. `metrics-url` 預設先用 `node-exporter`，若現場主要依賴 Netdata，可在 probe 參數中切換。
4. MVP 版故意不把 metrics reachability 納入 `DOWN`，因此若要主張整體監控鏈 availability，需第二輪再擴充判定。
5. `icclz1` 實測對 `harbor.iccl.local:8088` 存在 `connection refused`，因此 sentinel 目前改回 `python:3.12-slim`。

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

1. 先跑短版 `BASELINE -> CPU-M -> RECOVERY`，驗證 phase file 與 probe 結合。
2. 根據實測校正 `COMPUTE_LOOPS`、stress workers 與 memory bytes。
3. 補 `phase_summary` 與 runbook。
4. 規劃較長時間的 `6h` quick validation。
