# experiments_yolo: Single Pod Background-Load Fan-Cycle Experiment

本專案用來執行以下情境：

- 單一 YOLO serving pod
- request 採 closed-loop serial
- 不使用 concurrency
- background pods 關閉
- worker 端額外啟動 torch matrix GPU background load
- fan 在 `GPU_DEFAULT` 與固定低速間切換

## 目前環境對齊

- repo root: `/home/icclz2/Pre6G`
- worker SSH alias: `icclz1-gpu`
- worker repo: `/home/icclz1/gpu-tempctl-lab`
- focus deploy: `yolo26n-focus`
- background deploy: `yolo26n-bg-1`
- VM URL: `http://140.113.179.9:31888`
- Netdata URL: `http://140.113.179.9:32163`

## 已驗證狀態

2026-05-28 已完成短版 smoke test（`CYCLES=1` 的短 cycle 版本）：

- `rows=259`
- `success rate=1.0`
- `e2e mean=125.969 ms`
- `server mean=33.926 ms`
- `server total mean=45.921 ms`

測試輸出已於驗證後刪除。

2026-06-02 已在目前主機重新完成同等短版 smoke test：

- `rows=310`
- `success_rate=100%`
- `client_mean_ms=55.685`
- `client_p95_ms=64.100`
- `server_mean_ms=31.025`

測試輸出應在驗證後刪除。

## Execution Model

每個 cycle 包含：

1. `normal_hold`
2. `fault_hold`
3. `recovery_wait`

歷史上 `2026-05-28` 的短版驗證曾完成這三段並帶回 worker 端 `thermal_cycle` 日誌。
本輪 `2026-06-02` 也已重新完成這一步。

## How To Run

### Default

```bash
cd /home/icclz2/Pre6G
CC_PASSWORD='your_coolercontrol_password' bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh
```

### Short Smoke Test

```bash
cd /home/icclz2/Pre6G
NODE_SSH=icclz1-gpu TARGET_MODE=pod TIMEOUT_SEC=20 REPEAT=1 CYCLES=1 NORMAL_HOLD_SECONDS=5 FAULT_HOLD_SECONDS=5 RECOVERY_STABLE_SECONDS=5 RECOVERY_MAX_SECONDS=20 WORKLOAD_HEADROOM_SECONDS=10 VM_AGG_INTERVAL=1.0 bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh
```

### Loop Mode

適合把單次 `CYCLES=1` run 連續重跑，持續累積多個 `RUN_ID`。按 `Ctrl+C` 可停止下一輪。

```bash
cd /home/icclz2/Pre6G
CC_PASSWORD='your_coolercontrol_password' \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle_loop.sh
```

若本輪資料會用於 10-30s VM-derived telemetry early-warning，建議啟用 debug sample-age metadata：

```bash
cd /home/icclz2/Pre6G
DEBUG_OUTPUT=1 CC_PASSWORD='your_coolercontrol_password' LOOP_GAP_SECONDS=300 \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle_loop.sh
```

新版 collector 會將 VM query sample age summary 寫入 `vm_aggregator_timeseries.csv`，並將每條 PromQL query 的 sample timestamp / age 寫入 sidecar：

```text
vm_aggregator_timeseries.vm_query_samples.jsonl
```

### Loop Smoke Test

```bash
cd /home/icclz2/Pre6G
CC_PASSWORD='your_coolercontrol_password' \
NORMAL_HOLD_SECONDS=5 FAULT_HOLD_SECONDS=5 \
RECOVERY_STABLE_SECONDS=5 RECOVERY_MAX_SECONDS=20 \
WORKLOAD_HEADROOM_SECONDS=10 LOOP_GAP_SECONDS=10 \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle_loop.sh
```

## Outputs

每次 run 輸出到：

```text
autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/<RUN_ID>/
```

主要檔案：

- `experiment_config.txt`
- `measurement_raw.csv`
- `summary.txt`
- `bgload_cycle_analysis.txt`
- `cycle_phase_summary.csv`
- `overall_phase_summary.csv`
- `aligned_serial_thermal.csv`
- `thermal_cycle/worker_logs/thermal.csv`
- `thermal_cycle/worker_logs/summary.json`
- `vm_aggregator_timeseries.csv`
- `vm_aggregator_timeseries.vm_query_samples.jsonl`
- `vm_aggregator_training_features.csv`

## Offline Forecasting Analysis

本實驗的 forecasting-first 離線分析分三層：

1. Thermal / clock / latency forecasting 與 residual anomaly：

```bash
cd /home/icclz2/Pre6G
MPLCONFIGDIR=/tmp/matplotlib-pre6g ./iccl/bin/python \
  autoscale-source-split/02-experiment-layer/experiments_yolo/common/offline_bgload_forecasting_analysis.py \
  --results-root autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle \
  --out-dir autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/offline_forecasting_analysis
```

2. VM 主要負載預測，target 為 GPU util、VRAM usage、CPU usage、RAM usage：

```bash
cd /home/icclz2/Pre6G
MPLCONFIGDIR=/tmp/matplotlib-pre6g ./iccl/bin/python \
  autoscale-source-split/02-experiment-layer/experiments_yolo/common/offline_vm_load_forecasting.py \
  --results-root autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle \
  --out-dir autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/vm_load_forecasting_analysis
```

3. Load forecast residual 接續 thermal degradation early-warning：

```bash
cd /home/icclz2/Pre6G
MPLCONFIGDIR=/tmp/matplotlib-pre6g ./iccl/bin/python \
  autoscale-source-split/02-experiment-layer/experiments_yolo/common/offline_load_residual_thermal_bridge.py \
  --results-root autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle \
  --load-dir autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/vm_load_forecasting_analysis \
  --thermal-dir autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/offline_forecasting_analysis \
  --out-dir autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/load_residual_thermal_bridge_analysis
```

主要分析輸出目錄：

```text
autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/offline_forecasting_analysis/
autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/vm_load_forecasting_analysis/
autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/load_residual_thermal_bridge_analysis/
```

目前 `2026-07-02` bridge 實驗結論：`load_residual_only` 尚不足以 early-warning，主要可用訊號仍是 thermal / clock；`thermal_plus_load_residual` 可作為後續 ablation，但仍需更多純正常高負載、不同 workload intensity 與 open-loop request 資料才能支持未知根因泛化。

## Notes

- 背景負載來自 worker 端 `gpu-tempctl-lab`，不是 repo 內部腳本
- 現在 summary 階段不再依賴 `pandas`
- `analyze_single_pod_bgload_fan_cycle.py` 若缺 `pandas` 會 non-blocking，不影響主流程完成
- single-pod workflow 會暫時把 `yolo26n-bg-1` scale 到 `0`；驗證後應恢復原本三實例 layout
