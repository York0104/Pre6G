# Open-loop Load Thermal Execution Guide

## Dry-run

```bash
python autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/configs/openloop_load_thermal_campaign.example.json \
  --dry-run
```

## Preflight-only

```bash
python autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/configs/openloop_load_thermal_campaign.example.json \
  --preflight-only
```

## Open-loop Client Dry-run

```bash
python autoscale-source-split/02-experiment-layer/experiments_yolo/common/open_loop_request_client.py \
  --url http://127.0.0.1:8000/predict \
  --image /path/to/image.jpg \
  --duration-s 10 \
  --target-rps 2 \
  --max-inflight 4 \
  --output /tmp/openloop_client_raw.csv \
  --summary-output /tmp/openloop_client_1s_summary.csv \
  --manifest-output /tmp/openloop_client_manifest.json \
  --dry-run
```

## Cooling-Constrained Campaign Guard

Cooling-constrained campaign execution is not implemented in this runner. The following command must fail closed even if `CONFIRM_EXPERIMENT=YES` is present:

```bash
CONFIRM_EXPERIMENT=YES python autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config <operator-reviewed-config.json> \
  --run-campaign
```

`operator_max_gpu_temp_c` must be filled from local safety policy before any future live executor is enabled.

## Normal-only Live Smoke

This is the only live smoke path. It performs no fan control, no CoolerControl, no cooling intervention, and no Kubernetes scale/restart/delete.

Run this before any calibration sweep. Use one conservative low offered RPS and a short duration only to validate the data chain.

Use the dedicated operator template/checklist:

- `openloop_load_thermal_campaign/configs/normal_only_smoke.operator.template.json`
- `docs/NORMAL_ONLY_SMOKE_OPERATOR_CHECKLIST.md`

Pre-run manual checklist:

- `operator_max_gpu_temp_c` follows local device safety policy.
- Endpoint, image payload, node, and GPU identity are correct.
- No unexpected GPU workload is present.
- Telemetry can observe GPU temperature, SM clock, power, and utilization.
- The config contains no fan, CoolerControl, cooling intervention, or Kubernetes workload control action.

```bash
CONFIRM_NORMAL_SMOKE=YES python autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config <operator-reviewed-config.json> \
  --normal-only \
  --run-normal-smoke
```

Smoke success criteria:

- Scheduled arrivals match target offered RPS.
- `dropped_max_inflight` is near zero.
- Completion-binned throughput and timestamps are reasonable.
- No sustained timeout or error burst.
- GPU temperature stays below and not close to the operator limit.
- SM clock has no unexplained abnormal downclock.
- GPU, VM, and request timestamps align.
- Raw request log, arrival summary, completion summary, manifest, and safety record are retained.

If timeout, drop, or telemetry gap appears, do not increase RPS. Fix the data chain or client saturation first.

VM sample-age check:

```bash
python autoscale-source-split/02-experiment-layer/experiments_yolo/common/analyze_vm_sample_age.py \
  --run-dir <normal-smoke-run-dir>
```

Use `vm_sample_age_analysis/vm_sample_age_report_zh.md` before deciding whether VM-derived telemetry can be a primary 10-30s early-warning feature. The per-query sidecar is the authoritative source for VM sample timestamp / age; CSV debug counters such as `queries_recorded` are not sample age seconds.

## Normal-cooling Calibration

Calibration runs the configured `calibration.candidate_offered_rps` levels for short durations and does not auto-select final low/medium/high.

Only run calibration after the single normal-only smoke passes. Candidate levels should be repeated, with the same YOLO model, image mix, max-inflight, timeout, background workload setting, and normal cooling condition.

```bash
CONFIRM_NORMAL_SMOKE=YES python autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config <operator-reviewed-config.json> \
  --normal-only \
  --calibrate-normal
```

Offline summary:

```bash
python autoscale-source-split/02-experiment-layer/experiments_yolo/common/offline_normal_load_calibration_analysis.py \
  --input-root <calibration-output-root> \
  --out-dir <calibration-output-root>/calibration_analysis
```
