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

## Execution Model

每個 cycle 包含：

1. `normal_hold`
2. `fault_hold`
3. `recovery_wait`

在目前短版 smoke test 中，這三段都已實際執行過，並成功將 worker 端 `thermal_cycle` 日誌帶回 master。

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

## Notes

- 背景負載來自 worker 端 `gpu-tempctl-lab`，不是 repo 內部腳本
- 現在 summary 階段不再依賴 `pandas`
- `analyze_single_pod_bgload_fan_cycle.py` 若缺 `pandas` 會 non-blocking，不影響主流程完成
- single-pod workflow 會暫時把 `yolo26n-bg-1` scale 到 `0`；驗證後應恢復原本三實例 layout
