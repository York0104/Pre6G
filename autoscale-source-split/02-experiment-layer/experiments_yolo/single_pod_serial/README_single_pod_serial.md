# experiments_yolo: Single Pod Serial Service Experiment

本資料夾用於設計與執行單一 YOLO Pod 的 closed-loop serial request 實驗。

此實驗與 `saturation_multi_pod/` 的差異在於：

- 只保留一個 YOLO serving pod
- 不使用 concurrency 壓測
- client 僅在前一個 request 完成後，才送出下一個 request
- 觀察重點改為長時間 serial serving 下的 latency、throughput 與 GPU thermal/resource trend

預設 target mode 為 `service`，也就是 measurement client 會先打到 Kubernetes Service，再由 Service 轉送到唯一的後端 pod。這樣和既有 Task 3 的量測口徑較一致，也較接近真實服務情境。

## 1. Experiment Goal

本實驗要回答的問題是：

1. 單 pod、非 concurrency、closed-loop serial request 下，服務可達到多少自然 throughput。
2. 長時間持續服務時，`e2e_latency_ms`、`server_latency_ms`、`server_total_latency_ms` 是否隨溫度或功耗逐步漂移。
3. GPU temperature、power、utilization、VRAM 使用量是否會進入穩定區間。
4. 與多 pod saturation 實驗相比，單 pod 的 latency 與 GPU resource signature 有何差異。

## 2. Request Model

本實驗採用：

- `closed-loop`
- `serial`
- `successive requests`

也就是：

1. client 送出一個 request
2. 等待該 request 成功或失敗返回
3. 才送下一個 request

這和 Task 3 的 `concurrency > 1` / `open-loop-like high pressure` 不同。

## 3. Directory Structure

```text
experiments_yolo/
├── common/
│   ├── request_client_serial.py
│   ├── analyze_single_pod_serial.py
│   ├── plot_task3_full_timeline.py
│   └── plot_resource_overview.py
└── single_pod_serial/
    ├── README_single_pod_serial.md
    └── run_single_pod_serial_with_metrics.sh
```

## 4. Main Scripts

### 4.1 `common/request_client_serial.py`

單一 serial client。

特性：

- 每次只保留一個 in-flight request
- 上一筆完成後才送下一筆
- 輸出欄位盡量和 `request_client_parallel.py` 保持一致
- 額外增加：
  - `inter_request_gap_ms`
  - `loop_elapsed_ms`

### 4.2 `single_pod_serial/run_single_pod_serial_with_metrics.sh`

此腳本會：

1. scale focus deployment 到 `1`
2. scale background deployments 到 `0`
3. 蒐集 pod / deployment / event 狀態
4. 啟動 `nvidia-smi` 與 `kubectl top` 監控
5. 啟動 serial request client
6. 產生 `summary.txt`、`serial_analysis.txt`、`plots/`

## 5. Expected Outputs

每次 run 會輸出到：

`experiments/experiments_yolo/results/single_pod_serial/<RUN_ID>/`

主要檔案：

- `experiment_config.txt`
- `measurement_raw.csv`
- `measurement.log`
- `summary.txt`
- `serial_analysis.txt`
- `phase_summary.csv`
- `nvidia_smi_gpu_1s.csv`
- `kubectl_top_1s.log`
- `plots/fig*.png`
- `plots/gpu_resource_overview.png`

## 6. How To Run

### 6.1 Basic Run

進入專案根目錄後直接執行：

```bash
cd /home/iccls2/AutoScale
bash experiments/experiments_yolo/single_pod_serial/run_single_pod_serial_with_metrics.sh
```

此指令會使用預設值：

- `TARGET_MODE=service`
- `DURATION=1800`
- `TIMEOUT_SEC=20`
- `REPEAT=1`

並自動調整 deployment：

- `yolo26n-task3-focus -> replicas=1`
- `yolo26n-task3-bg -> replicas=0`

### 6.2 Example: 5-Minute Run

```bash
cd /home/iccls2/AutoScale
DURATION=300 TIMEOUT_SEC=30 REPEAT=10 \
bash experiments/experiments_yolo/single_pod_serial/run_single_pod_serial_with_metrics.sh
```

### 6.3 Example: Force Pod Mode

若要直接打單一 focus pod，而不是經過 service：

```bash
cd /home/iccls2/AutoScale
TARGET_MODE=pod DURATION=300 TIMEOUT_SEC=30 REPEAT=10 \
bash experiments/experiments_yolo/single_pod_serial/run_single_pod_serial_with_metrics.sh
```

### 6.4 Common Environment Variables

- `DURATION`
  - 實驗秒數，例如 `300`、`1800`
- `TIMEOUT_SEC`
  - 單一 request timeout 秒數
- `REPEAT`
  - 傳給 `/infer?repeat=...` 的 repeat 參數
- `TARGET_MODE`
  - `service` 或 `pod`
- `NAMESPACE`
  - 預設 `intent-lab`
- `NODE_SSH`
  - 用於收集遠端 `nvidia-smi`，預設 `icclz1@140.113.179.6`

### 6.5 Outputs After Run

執行完成後，結果會寫到：

```text
experiments/experiments_yolo/results/single_pod_serial/<RUN_ID>/
```

建議優先查看：

- `experiment_config.txt`
- `summary.txt`
- `serial_analysis.txt`
- `measurement_raw.csv`
- `nvidia_smi_gpu_1s.csv`
- `plots/`

## 7. Reused Common Tools

此實驗直接沿用：

- `common/plot_task3_full_timeline.py`
- `common/plot_resource_overview.py`

原因是：

- `measurement_raw.csv` schema 保持一致
- `nvidia_smi_gpu_1s.csv` 格式保持一致
- 即使沒有 `stable_windows.csv`，這兩個 plotter 仍可直接運作

## 8. Notes

- 這個實驗目前先不強依賴 `stable_windows.csv`
- 若後續要做「單 pod thermal steady-state window」分析，再另外新增專用 window finder
- 這版刻意不修改既有 `saturation_multi_pod/` 流程，避免和 Task 3 結果混淆
