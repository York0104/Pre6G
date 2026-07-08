# Pod-Level Protection A/B Runbook

Status: `prepared, not applied`

## Objective

在量測鏈穩定、且未保護版 `Phase 1` 已完成後，使用相同 phase ladder 重跑 protection 版，與未保護版做 A/B 比較。

## A/B Cases

Case A:

- base manifests
- no extra `PriorityClass`
- no protection overlay
- dynamic stress jobs use baseline inline definition from `stress_runner.sh`

Case B:

- `pod-protection` overlay enabled
- Sentinel `Guaranteed QoS`
- Sentinel high `PriorityClass`
- Stress job low `PriorityClass`
- dynamic stress jobs receive low-priority/resources through `STRESS_*` environment variables

## Apply Paths

Case A:

```bash
kubectl apply -k 02-experiment-layer/device_availability/manifests/base
```

Case B:

```bash
kubectl apply -k 02-experiment-layer/device_availability/manifests/overlays/pod-protection
```

Case B phase run:

```bash
cd /home/icclz2/Pre6G/autoscale-source-split
STRESS_PRIORITY_CLASS=device-availability-stress-low \
CPU_STRESS_REQUEST_CPU=500m \
CPU_STRESS_LIMIT_CPU=4 \
CPU_STRESS_REQUEST_MEMORY=64Mi \
CPU_STRESS_LIMIT_MEMORY=128Mi \
MEM_STRESS_REQUEST_CPU=250m \
MEM_STRESS_LIMIT_CPU=1 \
MEM_STRESS_REQUEST_MEMORY=256Mi \
MEM_STRESS_LIMIT_MEMORY=7Gi \
bash 02-experiment-layer/device_availability/run_phase1_quick_validation.sh phase1_quick_validation_protected
```

Rollback to base:

```bash
kubectl apply -k 02-experiment-layer/device_availability/manifests/base
```

Optional static stress manifest reference:

```bash
kubectl apply -k 02-experiment-layer/device_availability/manifests/stress-jobs
```

## Same Experiment Profile Requirement

A/B 時必須固定：

1. 同一 `phase ladder`
2. 同一 target node
3. 同一 `COMPUTE_LOOPS`
4. 同一 probe thresholds
5. 同一 stress workers / memory bytes

## Metrics To Compare

1. `DOWN` 次數
2. `DEGRADED` 次數
3. `sentinel_unreachable` 次數
4. `compute_check_timeout` 次數
5. `compute_ms` mean / p95 / p99 / max
6. `healthz_ms` p95 / p99 / max
7. Sentinel restart count
8. `Node Ready` interruption count
9. recovery latency after stress phase
