# Pod-Level Protection Checklist

Status: `prepared, not applied`

## Before Enabling Protection

1. Confirm the current line of work is not actively rolling out sentinel changes.
2. Confirm unprotected baseline or `Phase 1` result has been archived.
3. Confirm `kubectl apply -k manifests/base` returns the expected baseline objects.
   Base should restore sentinel only, without creating stress jobs.
4. Confirm the chosen `COMPUTE_LOOPS` and probe thresholds are frozen for the A/B run.

## During Protection Run

1. Confirm `PriorityClass` resources exist.
2. Confirm sentinel Pod shows the expected `priorityClassName`.
3. Confirm sentinel Pod shows requests = limits for CPU and memory.
4. Confirm stress jobs show the low-priority class.
5. Confirm the phase runner was started with the expected `STRESS_*` environment variables.
6. Confirm `availability.csv` is being written normally.

## After Protection Run

1. Archive output artifacts under a distinct run directory.
2. Record `DOWN / DEGRADED` counts for Case A vs Case B.
3. Record `compute_ms` and `healthz_ms` tail behavior.
4. Record whether sentinel restarts occurred.

## Rollback

Return to base:

```bash
kubectl apply -k 02-experiment-layer/device_availability/manifests/base
```

Then verify:

1. Sentinel no longer uses the protection `PriorityClass`
2. Stress jobs no longer use the low-priority `PriorityClass`
3. resources return to baseline manifest values
