# Open-loop Load Thermal Reproducibility Guide

## Rebuild Order

1. Run dry-run/preflight and archive generated `run_manifest.json`.
2. Calibrate normal-cooling low/medium/high offered RPS.
3. Collect normal-cooling high-load controls.
4. Only after safety review, collect cooling-constrained runs with the same offered-load profiles.
5. Build load-conditioned expected behavior from normal-cooling training runs only.
6. Evaluate residual and onset-level warning behavior on held-out runs/conditions.

## Leakage Checks

- No random row split.
- No `shuffle=True`.
- No phase/fan/intervention/run/cycle/profile/time identifiers in primary model features.
- No target-derived future latency or future telemetry in features.
- Thresholds and residual normal ranges are fit only on training normal-cooling data.

## Required Reports

- run inventory
- data quality summary
- telemetry gap summary
- load-conditioned residual distribution
- normal high-load false-positive rate
- cooling-constrained detection rate
- event-level early-warning audit
- negative-control and ablation summary
