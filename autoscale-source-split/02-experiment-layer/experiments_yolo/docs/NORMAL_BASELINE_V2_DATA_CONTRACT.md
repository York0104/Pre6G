# Normal Baseline v2 Data Contract

Normal Baseline v2 is the next normal-cooling open-loop dataset used to validate load-conditioned expected behavior before any matched cooling-constrained pilot.

It is a normal-cooling collection contract only. It does not permit fan mode changes, CoolerControl, Kubernetes scale/restart/delete, cooling intervention, or GPU stress orchestration.

## Required Manifest Fields

Every formal run must include:

- `campaign_id`
- `replicate_id`
- `target_offered_rps`
- `run_order`
- `warmup_start_ts`, `warmup_end_ts`
- `measurement_start_ts`, `measurement_end_ts`
- `client_start_ts`, `client_stop_ts`
- `endpoint_identity`
- `model`
- `image_set_hash`
- `node_gpu_identity.gpu_uuid`
- `background_workload_state`
- `telemetry_source_availability`
- `telemetry_sample_age_summary`
- `latency_target_policy`

If any required field is missing, the derived dataset must set `analysis_ineligible=true`. Such rows may remain in inventory outputs, but they must not enter formal held-out validation.

## Measurement Window

The manifest defines the official measurement window. Analysis must not infer the measurement window from run-id ordering or arbitrary elapsed-time thresholds.

Rows are formal-analysis eligible only when:

- `analysis_ineligible=false`
- `elapsed_s >= measurement_start_elapsed_s`
- `elapsed_s < measurement_end_elapsed_s`
- required telemetry for the target is present
- latency target quality policy is satisfied for latency targets

Warm-up and post-observation rows can be retained for diagnostics, but expected-behavior fitting and held-out scoring must use only measurement-window rows.

## Latency Target Policy

Primary latency target:

- `rolling_latency_p50` or `rolling_latency_mean`, depending on `latency_target_policy.primary_latency_target`

Tail latency targets:

- `rolling_latency_p95`
- `rolling_latency_p99`

Tail targets are valid only when `rolling_completion_count >= min_tail_samples`. The dataset must emit:

- `rolling_completion_count`
- `rolling_latency_window_s`
- `rolling_latency_min_samples`
- `latency_quality_status`

Low offered-RPS runs should use longer latency windows so the primary latency target is not dominated by one completion.

## Primary Feature Schema

Allowed primary load features:

- `target_offered_rps`
- `inflight_count_max`
- `client_backlog_or_schedule_miss`
- verified `background_workload_state`

Rules:

- `target_offered_rps` and `scheduled_request_count` must not both be primary predictors.
- VM `gpu_util_avg` remains `telemetry_semantic_pending` and must not be used as a primary feature.
- `completed RPS`, success rate, and latency history are observed service state, not external demand.
- nvidia-smi / DCGM GPU telemetry can be used as GPU state reference or model targets, not as a substitute for offered load.
- Phase, fan mode, intervention flag, run ID, cycle ID, profile ID, and absolute elapsed time are forbidden primary operational features.

## Validation Rules

Formal held-out validation must:

- use only manifest-valid measurement-window rows
- fit expected behavior and thresholds from training normal-cooling runs only
- avoid random row split
- avoid adjacent rows from the same run crossing train/test
- use debounced anomaly episodes as the main false-alarm metric
- keep point-wise exceedance and short-run FA/hour only as exploratory sensitivity outputs
- enable Leave-One-Replicate-Per-Load-Level-Out only when `replicate_id` is complete and read from manifest

## Current Status

Existing v1 normal runs are useful for method development and measurement audit, but they lack complete v2 manifest metadata. They must be marked analysis-ineligible for formal Normal Baseline v2 held-out validation.
