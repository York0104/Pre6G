# D1-D4 Diagnosis Runbook

這份 runbook對應失效來源切分診斷矩陣。

## Cases

`D1`

- `healthz-only baseline`

`D2`

- `compute-check-only baseline`

`D3`

- `healthz + compute-check`
- observer / local probes 錯開 `1s`

`D4`

- `healthz + compute-check + mild CPU`

## Evidence Collected

1. Observer side:
   - HTTP code
   - curl exit
   - connect / starttransfer / total timing
   - coarse error class
2. Sentinel side:
   - request log lines from stdout
   - endpoint / thread / elapsed ms
3. Kubernetes:
   - DaemonSet snapshot
   - Pod snapshot
   - events
4. Worker local:
   - localhost `127.0.0.1:18080` continuous probe via `kubectl exec`

## Example

```bash
cd /home/icclz2/Pre6G/autoscale-source-split
ITERATIONS=180 INTERVAL_SECONDS=5 \
bash 02-experiment-layer/device_availability/diagnostics/run_diagnosis_case.sh D1
```

四個 case 依序執行：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split
bash 02-experiment-layer/device_availability/diagnostics/run_diagnosis_case.sh D1
bash 02-experiment-layer/device_availability/diagnostics/run_diagnosis_case.sh D2
bash 02-experiment-layer/device_availability/diagnostics/run_diagnosis_case.sh D3
bash 02-experiment-layer/device_availability/diagnostics/run_diagnosis_case.sh D4
```
