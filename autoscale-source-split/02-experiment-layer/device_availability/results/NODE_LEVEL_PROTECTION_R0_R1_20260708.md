# Node-Level Protection R0/R1 Report

Date: `2026-07-08`

Target node:

- `icclz1`

Observer:

- `icclz2`

## Scope

本報告整理兩個 node-level protection 前置 round：

1. `R0`: seal `Phase 2 protected baseline`
2. `R1`: pod memory limit validation

這兩輪都建立在既有 pod-level protected sentinel 條件上：

- sentinel priority class: `device-availability-sentinel-high`
- sentinel resources: `cpu=250m`, `memory=128Mi` with equal request / limit

## R0: Phase 2 Protected Baseline

Reference:

- `docs/PHASE2_PROTECTED_BASELINE_SUMMARY_20260708.md`

Sealed baseline:

- run id: `phase2_formal_20260708_protected`

Key metrics:

| Metric | Value |
| --- | --- |
| observation_duration_s | `21602.0` |
| samples_total | `3883` |
| confirmed_outage_events | `0` |
| confirmed_outage_availability_percent | `100.0%` |
| degraded_per_1000_samples | `10.044` |
| sentinel_unreachable_per_1000_samples | `4.378` |
| compute_latency_high_per_1000_samples | `4.893` |
| compute_timeout_or_failed_per_1000_samples | `0.773` |

Interpretation:

1. 這份 baseline 作為後續 `R1 / R2 / R3 / R4` 的 protected 對照組。
2. baseline 已證明 availability / reachability 可成立，但 mixed stress 與 recovery latency tail 仍存在。

## R1: Pod Memory Limit Validation

Run id:

- `r1_pod_memory_limit_20260708_protected`

Profile:

```text
BASELINE       10 min
MEM-contained  20 min
RECOVERY-1     10 min
MEM-boundary   20 min
FINAL-RECOVERY 10 min
Total          70 min
```

Dynamic stress settings:

- `STRESS_PRIORITY_CLASS=device-availability-stress-low`
- `MEM_STRESS_REQUEST_CPU=250m`
- `MEM_STRESS_LIMIT_CPU=1`
- `MEM_STRESS_REQUEST_MEMORY=256Mi`
- `MEM_STRESS_LIMIT_MEMORY=7Gi`
- `MEM_CONTAINED_BYTES=6G`
- `MEM_BOUNDARY_BYTES=7G`

### Observation Window

| Field | Value |
| --- | --- |
| observation_start | `2026-07-08T02:44:42+00:00` |
| observation_end | `2026-07-08T03:54:44+00:00` |
| observation_duration_s | `4202.0` |
| samples_total | `786` |
| effective_sample_interval_s | `5.353` |

### Outcome Summary

| Metric | Value |
| --- | --- |
| samples_down | `0` |
| samples_degraded | `1` |
| confirmed_outage_events | `0` |
| confirmed_outage_availability_percent | `100.0%` |
| sentinel_unreachable_per_1000_samples | `0.000` |
| compute_latency_high_per_1000_samples | `1.272` |
| compute_timeout_or_failed_per_1000_samples | `0.000` |

Phase breakdown:

| Phase | Samples | UP | DEGRADED | Notes |
| --- | ---: | ---: | ---: | --- |
| `BASELINE` | `110` | `109` | `1` | single `compute_latency_high` |
| `MEM-contained` | `224` | `224` | `0` | no anomaly observed |
| `RECOVERY-1` | `113` | `113` | `0` | no anomaly observed |
| `MEM-boundary` | `225` | `225` | `0` | no probe degradation observed |
| `FINAL-RECOVERY` | `112` | `112` | `0` | no anomaly observed |

### Workload Containment Evidence

Observed evidence:

1. `pod_watch.log` recorded `OOMKilled` transitions for `device-avail-mem-stress-*` during `MEM-boundary`.
2. `pod_watch.log` shows `6` distinct `OOMKilled` stress pod names during that boundary phase window.
3. Despite workload failure, the probe side remained `UP` for all `MEM-boundary` samples.

Interpretation:

- `pod memory limit` successfully turned aggressive memory pressure into workload-level failure rather than node-level failure.
- 這輪的主要有效證據不是 stress workload 成功跑滿，而是 failure 被 containment 在 stress pod。

### Node / Sentinel Evidence

Observed evidence:

1. `node_describe_before.log` 與 `node_describe_after.log` 均顯示:
   - `Ready=True`
   - `MemoryPressure=False`
   - `DiskPressure=False`
   - `PIDPressure=False`
2. sentinel pod 在整輪維持 `Running`，未觀察到 restart。
3. `sentinel_unreachable_per_1000_samples = 0.000`。

Interpretation:

- 本輪未觀察到 `Node NotReady`、sentinel confirmed outage 或 node pressure escalation。
- `R1` 的 pass criteria 在目前證據下可視為成立。

## Decision

`R0`: completed

- `phase2_formal_20260708_protected` 已封存為 `P2 Pod-level protected baseline`

`R1`: completed

- `r1_pod_memory_limit_20260708_protected` 已證明 memory stress failure 可被限制在 workload pod 層

## Residual Notes

1. `MEM-boundary` 期間觀察到多個 `OOMKilled` stress pod instance；若後續需要更乾淨的 workload 行為 accounting，可再單獨檢查 Job retry / replacement semantics。
2. 這輪結果支持往 `R2 short evictionHard validation` 前進，但不代表 `evictionHard` 或 `systemReserved` 已被驗證。
3. 目前 availability 定義仍是 `confirmed outage` 口徑，應與 performance / latency tail 分開解讀。
