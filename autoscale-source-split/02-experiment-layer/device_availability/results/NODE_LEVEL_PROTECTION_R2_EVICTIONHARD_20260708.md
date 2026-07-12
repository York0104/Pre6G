# R2 evictionHard Short Validation

Status: `template; R2f safety profile completed, R2g effectiveness retry pending`

Run id:

- `r2_evictionhard_short_20260708_protected`

Prior attempts maintained reachability but did not observe `MemoryPressure` or `Evicted` stress Pods. The `r2c` attempt also hit `pull QPS exceeded`; it must not be presented as evidence that `evictionHard` worked.

`r2f_evictionhard_short_20260711_protected` completed with clean baseline and full profile: zero confirmed outage, one transient degraded sample, no `MemoryPressure` or `Evicted` Pod, and three distinct stress Pod `OOMKilled` events. It is availability/containment evidence, not evictionHard-effectiveness evidence. `r2g` changes only the stress memory limit from `3Gi` to `4Gi`.

## Configuration

- evictionHard:
- sentinel QoS:
- sentinel PriorityClass:
- stress PriorityClass:
- per-pod memory request:
- per-pod memory limit:
- per-pod vm-bytes:
- parallelism:
- aggregate requested memory:
- aggregate limit:
- approx aggregate vm-bytes:

## Preflight

- node Ready before:
- sentinel running before:
- stress jobs cleared before:
- k3s config backup path:
- k3s agent config merge method:

## Availability Summary

- samples_total:
- samples_down:
- samples_degraded:
- confirmed_outage_events:
- confirmed_outage_availability_percent:

## Node Pressure Summary

- MemoryPressure observed:
- MemoryPressure duration:
- min MemAvailable:
- Evicted pod count:
- OOMKilled pod count:
- host OOM:

## Phase Summary

| Phase | Samples | DOWN | DEGRADED | Key observation |
| --- | ---: | ---: | ---: | --- |
| `BASELINE` |  |  |  |  |
| `MEM-AGG-M` |  |  |  |  |
| `RECOVERY-1` |  |  |  |  |
| `MEM-AGG-H` |  |  |  |  |
| `RECOVERY-2` |  |  |  |  |
| `MIX-AGG-M` |  |  |  |  |
| `FINAL-RECOVERY` |  |  |  |  |

## Evicted Pods

| Pod | Phase | Reason | PriorityClass | QoS | Request | Limit |
| --- | --- | --- | --- | --- | --- | --- |

## OOMKilled Pods

| Pod | Phase | Reason | PriorityClass | QoS | Request | Limit |
| --- | --- | --- | --- | --- | --- | --- |

## Sentinel Protection Result

- sentinel restartCount:
- sentinel evicted:
- sentinel OOMKilled:
- sentinel final state:

## Host Safety

- `k3s-agent` restart:
- `containerd` restart:
- kernel OOM log summary:
- non-stress workload eviction observed:

## Comparison With R1

- R1 result:
- R2 difference:
- did `evictionHard` actually participate:

## Decision

- pass / retry / fail

## Interpretation

- did pressure remain contained:
- did node management remain available:
- can the experiment proceed to `R3 6h`:
