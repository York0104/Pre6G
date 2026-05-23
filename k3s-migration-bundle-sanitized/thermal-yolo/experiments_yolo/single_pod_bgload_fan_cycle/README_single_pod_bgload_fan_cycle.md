# experiments_yolo: Single Pod Background-Load Fan-Cycle Experiment

本專案用來執行以下情境：

- 單一 YOLO serving pod
- request 採 closed-loop serial
- 不使用 concurrency
- background pods 關閉
- worker 端額外啟動 torch matrix GPU background load
- fan 只在兩種狀態間切換：
  - `GPU_DEFAULT`
  - 固定 `5%`
- 每個 cycle 包含：
  - `normal_hold` 15 分鐘
  - `fault_hold` 15 分鐘
  - `recovery_wait`：恢復自動後，等溫度回到穩定區間再開始下一個 cycle

## 1. Design Goal

這個專案要回答：

1. 在有 background torch matrix load 的情況下，是否能把正常風扇的溫度維持在 `50-70℃`
2. 當 fan 固定到 `5%` 時，是否能升到 `90℃` 以上
3. `server latency` / `e2e latency` 是否會隨 cycle 切換與溫度變化而退化
4. 多個 cycle 之間，是否出現熱累積或恢復不足

## 2. Execution Model

每個 cycle 的 phase：

1. `normal_hold`
   - fan = `GPU_DEFAULT`
   - 背景 torch GPU load 持續運行
   - 預設 15 分鐘
2. `fault_hold`
   - fan = 固定 `5%`
   - 同一份背景 load 持續運行
   - 預設 15 分鐘
3. `recovery_wait`
   - fan 恢復 `GPU_DEFAULT`
   - 溫度需連續落在 `[NORMAL_TEMP_MIN_C, NORMAL_TEMP_MAX_C]`
   - 達到 `RECOVERY_STABLE_SECONDS` 才進下個 cycle
   - 若超過 `RECOVERY_MAX_SECONDS`，則記錄 timeout 並進下個 cycle

## 3. Background Load Control

背景負載沿用 worker 端 `fan_control_lab/gpu_load_torch.py`。

可調參數：

- `BG_SIZE`
- `BG_DUTY`
- `BG_PERIOD_MS`

建議把這三個參數當作校準旋鈕：

- 若正常風扇溫度太低，增加 `BG_DUTY` 或 `BG_SIZE`
- 若正常風扇已經超過 `70℃`，降低 `BG_DUTY` 或增加 `BG_PERIOD_MS`
- 若 fault phase 上不去 `90℃`，增加背景負載

## 4. How To Run

### 4.1 Default

```bash
cd /home/iccls2/AutoScale
CC_PASSWORD='your_coolercontrol_password' \
bash experiments/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh
```

預設值：

- `CYCLES=3`
- `NORMAL_HOLD_SECONDS=900`
- `FAULT_HOLD_SECONDS=900`
- `RECOVERY_STABLE_SECONDS=60`
- `RECOVERY_MAX_SECONDS=900`
- `FIXED_FAN_PCT=5`
- `NORMAL_TEMP_MIN_C=50`
- `NORMAL_TEMP_MAX_C=70`
- `FAULT_TEMP_TARGET_C=90`
- `BG_SIZE=4096`
- `BG_DUTY=1.0`
- `BG_PERIOD_MS=100`

### 4.2 Example: One Cycle Smoke Test

```bash
cd /home/iccls2/AutoScale
CC_PASSWORD='your_coolercontrol_password' \
CYCLES=1 \
NORMAL_HOLD_SECONDS=300 \
FAULT_HOLD_SECONDS=300 \
RECOVERY_MAX_SECONDS=300 \
bash experiments/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh
```

### 4.3 Example: Tune Background Load

```bash
cd /home/iccls2/AutoScale
CC_PASSWORD='your_coolercontrol_password' \
CYCLES=1 \
BG_DUTY=0.70 \
BG_PERIOD_MS=150 \
bash experiments/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh
```

## 5. Outputs

每次 run 輸出到：

`experiments/experiments_yolo/results/single_pod_bgload_fan_cycle/<RUN_ID>/`

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
- `plots/bgload_cycle_temp_fan_timeseries.png`
- `plots/bgload_cycle_temp_latency_overview.png`
- `plots/cycles/cycle_001_temp_fan_timeseries.png`
- `plots/cycles/cycle_001_temp_latency_overview.png`
- `plots/cycles/cycle_002_*.png`, `cycle_003_*.png`, ...
- `plots/fig*.png`
- `plots/gpu_resource_overview.png`

## 6. Plot Design

- `plots/bgload_cycle_temp_fan_timeseries.png`
  - 全部 cycles 的總圖
  - 時間對 `fan / temp / SM clock / GPU util`
- `plots/bgload_cycle_temp_latency_overview.png`
  - 全部 cycles 的總圖
  - 時間對 `fan / temp / server latency / e2e latency`
- `plots/cycles/cycle_<N>_temp_fan_timeseries.png`
  - 單一 cycle 的分圖
- `plots/cycles/cycle_<N>_temp_latency_overview.png`
  - 單一 cycle 的分圖

## 7. Notes

- `duration` 不再是主要輸入；這個專案改用 `CYCLES`
- measurement client 會持續送 closed-loop serial request，直到 thermal cycle 結束
- 每個 cycle 都會在 worker 端 summary 中標記：
  - `normal_mean_in_band`
  - `fault_max_ge_target`
- 如果這兩個檢查沒過，通常表示背景負載還需要再校準
