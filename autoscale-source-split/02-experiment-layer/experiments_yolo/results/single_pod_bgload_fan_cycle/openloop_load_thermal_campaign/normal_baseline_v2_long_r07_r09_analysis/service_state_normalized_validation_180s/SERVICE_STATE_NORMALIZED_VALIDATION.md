# Service-State Normalized Held-Out Normal Validation

## Scope

This is an offline post-processing audit over held-out predictions. It does not rerun live experiments and does not use fan, phase, intervention, run ID, or future telemetry as model features.

## Method

- calibration_window_s: `180`
- For each held-out run, latency residual offset is estimated only from the initial calibration window of that same run.
- The calibration window is excluded from formal episode scoring.
- GPU temperature and SM clock residuals are not offset-normalized.
- Composite risk is recomputed using normalized latency residuals plus original GPU-state residuals.

## Summary

- input validation dir: `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_long_r07_r09_analysis/heldout_long_normal_residual_validation`
- scored rows: `5400`
- latency offset rows: `12`
- composite total episodes after calibration: `0`
- r02 rolling_latency_p50 episodes after calibration: `0`

## Interpretation

If r02 latency episodes disappear after this online offset calibration, the earlier instability is best interpreted as normal service-state baseline shift rather than thermal-performance anomaly. This does not prove deployable generalization; it only shows that a run-local healthy calibration layer may be needed before latency residual is used as a primary warning signal.
