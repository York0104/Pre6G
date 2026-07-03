# Matched Cooling-Constrained Pilot Contract

This contract defines the minimum method requirements before any matched cooling-constrained pilot is considered. It does not authorize live cooling intervention by itself.

## Current Gate

The current open-loop runner keeps cooling-constrained `--run-campaign` fail-closed. A pilot may be designed from this contract, but live execution requires a separately implemented and reviewed executor.

## Required Matched Design

Each matched pair must use:

- same endpoint identity
- same YOLO model and container image
- same input image set hash
- same target offered RPS
- same max-inflight and timeout
- same payload mix
- same background workload state
- same node and GPU identity
- same telemetry collectors

The only planned treatment difference may be the cooling condition. Fan / cooling metadata is allowed for experiment documentation and event alignment, but it must not become a primary operational model feature.

## Required Timing Contract

Every pilot run must record these manifest boundaries:

- `warmup_duration_s = 180`
- `measurement_duration_s = 900`
- `post_observation_duration_s = 30`
- `run_local_healthy_calibration_window_s = 180`

Latency residual scoring must exclude the initial healthy calibration window. Thermal and clock telemetry from the calibration window may be used for run-state diagnostics, but target labels or future degradation information must not be used to set thresholds.

## Required Normal Baseline Evidence

Before pilot:

- at least 3 long normal-cooling replicates
- no safety aborts
- complete request logs and arrival/completion summaries
- VM sample-age summary available
- nvidia-smi telemetry available
- no raw manifest gaps
- latency p50 / p95 episodes equal 0 after 180s run-local healthy calibration

## Pilot Readiness Decision

Run:

```bash
./iccl/bin/python autoscale-source-split/02-experiment-layer/experiments_yolo/common/offline_matched_pilot_readiness_audit.py \
  --normal-long-analysis-dir autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_long_r07_r09_analysis \
  --out-dir autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/matched_pilot_readiness_audit
```

The only acceptable readiness outcome before design work is:

```text
method_ready_but_live_cooling_executor_still_fail_closed
```

## Not Yet Claimable

- Cross-environment generalization is not proven.
- Unknown-root-cause anomaly detection is not proven.
- NVIDIA thermal throttling mechanism is not proven without P-state / throttle reason / performance-cap telemetry.
- Raw cross-run latency residual without run-local calibration is not a valid primary warning signal.
