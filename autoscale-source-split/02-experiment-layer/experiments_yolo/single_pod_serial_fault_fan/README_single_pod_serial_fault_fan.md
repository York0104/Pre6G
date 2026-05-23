# experiments_yolo: Single Pod Serial Fault-Fan Experiment

本資料夾用於設計與執行以下情境：

- 單一 YOLO serving pod
- request 採 closed-loop serial
- 不使用 concurrency
- background pods 關閉
- worker 端 fan control 固定在低轉速
- 預設固定 `5%` 直到實驗結束
- 結束時自動恢復 `GPU_DEFAULT`
- 預設 `FAULT_HOLD_SECONDS=1800`，也就是約 30 分鐘高溫 / 低風扇實驗

## 1. Design Goal

本實驗要回答：

1. 單 pod、serial service 下，當 worker fan mode 切到 fault mode 時，溫度會升到哪裡。
2. `e2e_latency_ms`、`server_latency_ms`、`server_total_latency_ms` 是否隨溫度或 fan 降低而退化。
3. 高溫 phase 與正常 phase 相比，power / util / fan / latency 的差異為何。

## 2. Fan Control Note

目前此專案預設不再依 target temperature 做動態溫控切換，而是改成：

- 直接用 CoolerControl manual speed 固定 GPU fan
- 預設 `FIXED_FAN_PCT=5`
- 直到 run 結束後才 restore 成 `GPU_DEFAULT`

這樣的目的是讓：

- 溫度自然上升
- fan 不再因為 supervisor 覺得「太冷」而跳到 `15% / 20% / 25%`
- 單 pod serial latency 可以直接對照固定低風扇條件

如果之後你要改成別的固定值，可在執行時覆蓋：

```bash
FIXED_FAN_PCT=10 ...
```

## 3. Project Structure

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

## 4. How To Run

### 4.1 Default 30-Minute Fault-Fan Run

```bash
cd /home/iccls2/AutoScale
CC_PASSWORD='your_coolercontrol_password' \
bash experiments/experiments_yolo/single_pod_serial_fault_fan/run_single_pod_serial_fault_fan.sh
```

預設值：

- `TARGET_MODE=service`
- `THERMAL_CONTROL_MODE=fixed_manual`
- `FIXED_FAN_PCT=5`
- `WARMUP_SECONDS=0`
- `NORMAL_HOLD_SECONDS=0`
- `FAULT_HOLD_SECONDS=1800`
- `REPEAT=10`

### 4.2 Example: Explicit 30 Minutes

```bash
cd /home/iccls2/AutoScale
CC_PASSWORD='your_coolercontrol_password' \
FAULT_HOLD_SECONDS=1800 \
REPEAT=10 \
TIMEOUT_SEC=30 \
bash experiments/experiments_yolo/single_pod_serial_fault_fan/run_single_pod_serial_fault_fan.sh
```

### 4.3 Example: Override Fixed Fan Percentage

```bash
cd /home/iccls2/AutoScale
CC_PASSWORD='your_coolercontrol_password' \
FIXED_FAN_PCT=10 \
FAULT_HOLD_SECONDS=1800 \
bash experiments/experiments_yolo/single_pod_serial_fault_fan/run_single_pod_serial_fault_fan.sh
```

## 5. Outputs

每次 run 輸出到：

`experiments/experiments_yolo/results/single_pod_serial_fault_fan/<RUN_ID>/`

主要檔案：

- `experiment_config.txt`
- `measurement_raw.csv`
- `summary.txt`
- `fault_fan_analysis.txt`
- `thermal_phase_summary.csv`
- `aligned_serial_thermal.csv`
- `nvidia_smi_gpu_1s.csv`
- `thermal_cycle/worker_logs/thermal.csv`
- `plots/fault_fan_temp_fan_timeseries.png`
  - 時間對 `fan / temp / SM clock / GPU util`
- `plots/fault_fan_temp_latency_overview.png`
  - 時間對 `fan / temp / server latency / e2e latency`
- `plots/fig*.png`
- `plots/gpu_resource_overview.png`

## 6. Execution Model

1. scale `yolo26n-task3-focus -> 1`
2. scale `yolo26n-task3-bg -> 0`
3. measurement client 以 serial closed-loop 持續打 `service`
4. 同步啟動 worker 端 fixed-fan logger
5. 依 thermal log phase 對齊 request latency 與資源資料

## 7. Notes

- 這個專案保留 `service mode` 預設，和既有 Task 3 口徑一致
- 若只想看單 pod 本體，也可設 `TARGET_MODE=pod`
- 若要改低風扇百分比，請覆寫 `FIXED_FAN_PCT`
