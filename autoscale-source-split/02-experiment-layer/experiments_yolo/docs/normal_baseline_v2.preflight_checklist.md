# Normal Baseline v2 Preflight Checklist

Run this checklist before any `--run-normal-smoke --normal-only` execution.

Do not run live collection unless all items are confirmed by the operator.

## Operator Metadata

- `campaign_id` is set and unique for this dataset batch.
- `replicate_id` is set explicitly. It is not inferred from run order.
- `run_order` is set.
- `target_offered_rps` matches the intended workload profile.
- `warmup_duration_s`, `measurement_duration_s`, and `post_observation_duration_s` are reviewed.
- `operator_max_gpu_temp_c` is set from local safety policy.

## Service Identity

- Endpoint URL points to the intended YOLO service.
- Endpoint namespace/service identity is recorded.
- Model name and container image are recorded.
- Payload image list is fixed and reviewable.
- Image-set hash will be written to run manifest.

## Node / GPU Identity

- Node name is correct.
- GPU UUID is recorded.
- GPU model/index are recorded if available.
- No unexpected GPU workload is present.
- Background workload state is recorded and not controlled by this runner.

## Telemetry

- nvidia-smi telemetry is reachable.
- VM aggregator sidecar sample timestamp / age is enabled.
- Telemetry freshness threshold is configured.
- P-state / throttle reason / performance-cap reason gaps are documented if unavailable.

## Safety Boundary

- No fan mode change.
- No CoolerControl command.
- No cooling intervention.
- No Kubernetes scale/restart/delete.
- No long GPU stress.
- Live execution requires both `--normal-only` and `CONFIRM_NORMAL_SMOKE=YES`.

## Recommended Preflight Commands

```bash
cd /home/icclz2/Pre6G

./iccl/bin/python \
  autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/configs/normal_baseline_v2.operator.template.json \
  --dry-run \
  --normal-only

./iccl/bin/python \
  autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config path/to/operator-reviewed-normal-baseline-v2.json \
  --preflight-only \
  --normal-only
```

Do not use `--run-campaign`. Cooling-constrained execution remains out of scope.
