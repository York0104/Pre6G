# Open-loop campaign execution plan

- run_id: `openloop_20260703_095642`
- mode: `normal_cooling_calibration`
- runner role: `normal_cooling_planner_preflight_executor`
- live executor status: `normal_only_executor_available`
- live execution started: `False`
- no fan control executed: `True`

## Planned matrix

| workload | cooling condition | replicate | target_rps | duration_s | max_inflight |
|---|---|---:|---:|---:|---:|
| replicated_normal_baseline_seed | normal_cooling | 1 | 0.5 | 60 | 4 |

## Safety

- Cooling-constrained `--run-campaign` fails closed because that executor is not implemented.
- Normal-only smoke/calibration requires `--normal-only` and `CONFIRM_NORMAL_SMOKE=YES`.
- Normal-only execution must not perform fan control, CoolerControl, cooling intervention, or Kubernetes scale/restart/delete.
- Missing telemetry, control failure, service outage, or temperature safety breach must abort fail-closed.
