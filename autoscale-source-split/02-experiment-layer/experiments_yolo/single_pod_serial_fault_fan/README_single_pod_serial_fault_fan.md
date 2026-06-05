# experiments_yolo: Single Pod Serial Fault-Fan Experiment

本資料夾用於設計與執行以下情境：

- 單一 YOLO serving pod
- request 採 closed-loop serial
- 不使用 concurrency
- background pods 關閉
- worker 端 fan control 固定在低轉速
- 預設固定 `5%` 直到實驗結束
- 結束時自動恢復 `GPU_DEFAULT`

## 目前環境對齊

- repo root: `/home/icclz2/Pre6G`
- worker SSH alias: `icclz1-gpu`
- worker repo: `/home/icclz1/gpu-tempctl-lab`
- focus deploy: `yolo26n-focus`
- background deploy: `yolo26n-bg-1`
- VM URL: `http://140.113.179.9:31888`
- Netdata URL: `http://140.113.179.9:32163`

## 已驗證狀態

2026-05-28 已完成短版 smoke test（`TARGET_MODE=pod`、`FAULT_HOLD_SECONDS=10`）：

- `rows=89`
- `success rate=1.0`
- `e2e mean=113.141 ms`
- `server mean=17.566 ms`
- `server total mean=33.028 ms`

測試輸出已於驗證後刪除。

2026-06-02 已在目前主機重新完成同等短版 smoke test：

- `rows=235`
- `success_rate=100%`
- `client_mean_ms=42.322`
- `client_p95_ms=49.052`
- `server_mean_ms=16.746`

測試輸出應在驗證後刪除。

## Fan Control Note

目前此專案預設不再依 target temperature 做動態溫控切換，而是改成：

- 直接用 CoolerControl manual speed 固定 GPU fan
- 預設 `FIXED_FAN_PCT=5`
- run 結束後 restore 成 `GPU_DEFAULT`

## Project Structure

```text
experiments_yolo/
├── common/
│   ├── request_client_serial.py
│   ├── run_thermal_cycle_from_master.sh
│   ├── analyze_single_pod_serial_fault_fan.py
│   └── plot_single_pod_serial_fault_fan.py
└── single_pod_serial_fault_fan/
    ├── README_single_pod_serial_fault_fan.md
    └── run_single_pod_serial_fault_fan.sh
```

## How To Run

### Default Run

```bash
cd /home/icclz2/Pre6G
CC_PASSWORD='your_coolercontrol_password' bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial_fault_fan/run_single_pod_serial_fault_fan.sh
```

### Short Smoke Test

```bash
cd /home/icclz2/Pre6G
NODE_SSH=icclz1-gpu TARGET_MODE=pod TIMEOUT_SEC=20 REPEAT=1 WARMUP_SECONDS=0 NORMAL_HOLD_SECONDS=0 FAULT_HOLD_SECONDS=10 VM_AGG_INTERVAL=1.0 bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial_fault_fan/run_single_pod_serial_fault_fan.sh
```

## Outputs

每次 run 輸出到：

```text
autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_serial_fault_fan/<RUN_ID>/
```

主要檔案：

- `experiment_config.txt`
- `measurement_raw.csv`
- `summary.txt`
- `fault_fan_analysis.txt`
- `thermal_phase_summary.csv`
- `aligned_serial_thermal.csv`
- `nvidia_smi_gpu_1s.csv`
- `thermal_cycle/worker_logs/thermal.csv`

## Notes

- 現在 summary 階段不再依賴 `pandas`
- `analyze_single_pod_serial_fault_fan.py` 若缺 `pandas` 會 non-blocking，不影響主流程完成
- single-pod workflow 會暫時把 `yolo26n-bg-1` scale 到 `0`；驗證後應恢復原本三實例 layout
