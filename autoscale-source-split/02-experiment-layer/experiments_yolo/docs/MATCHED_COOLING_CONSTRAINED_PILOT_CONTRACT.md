# Matched Cooling-Constrained Pilot Contract

This contract defines the minimum method requirements before any matched cooling-constrained pilot is considered. It does not authorize live cooling intervention by itself.

## Current Gate

The current open-loop runner supports a narrow cooling-only SSH supervisor for the matched pilot. It does not use the legacy background-load fan-cycle runner, does not start torch background load, and does not run Kubernetes scale/restart/delete.

Live execution is still gated by `CONFIRM_EXPERIMENT=YES`, `CC_PASSWORD`, operator temperature threshold, r07-r09 readiness evidence, and `GPU_DEFAULT` restore policy. Without those gates, `--run-campaign` fails closed.

The reviewed design path now starts from:

```bash
./iccl/bin/python autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/configs/matched_cooling_constrained_pilot.operator.template.json \
  --preflight-only
```

This writes a preflight/recovery review package only. It does not run fan control, CoolerControl, Kubernetes control, GPU stress, or a cooling-constrained pilot.
The repository config is an operator template with placeholders; live execution requires a private local copy with site-specific endpoint, node/GPU identity, SSH alias, worker repo, and telemetry URLs filled in.

The live pilot command is intentionally explicit:

```bash
CONFIRM_EXPERIMENT=YES CC_PASSWORD='operator-provided' \
./iccl/bin/python autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/configs/matched_cooling_constrained_pilot.operator.template.json \
  --run-campaign
```

The runner must fail closed if `CC_PASSWORD` is absent.

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

## Required Preflight Artifacts

A matched-pilot preflight must produce:

- `matched_cooling_pilot_preflight.json`
- `matched_cooling_recovery_plan.json`
- `control_event_log.dryrun.jsonl`
- `MATCHED_COOLING_PILOT_PREFLIGHT.md`

The preflight must show:

- `live_execution_authorized=false`
- `live_execution_authorized=false` in dry-run/preflight artifacts
- `live_executor_status=cooling_only_executor_available_requires_confirm_and_cc_password`
- `restore_target=GPU_DEFAULT`
- normal-readiness evidence loaded from the r07-r09 readiness audit
- no primary-model use of phase, fan mode, fan speed, intervention flag, run ID, cycle ID, elapsed time, or profile ID

## Not Yet Claimable

- Cross-environment generalization is not proven.
- Unknown-root-cause anomaly detection is not proven.
- NVIDIA thermal throttling mechanism is not proven without P-state / throttle reason / performance-cap telemetry.
- Raw cross-run latency residual without run-local calibration is not a valid primary warning signal.
