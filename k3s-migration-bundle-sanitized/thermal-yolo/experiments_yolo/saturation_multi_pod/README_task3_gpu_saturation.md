# experiments_yolo: Task 3 GPU Saturation Experiment

本資料夾用於執行 YOLO26 Kubernetes GPU 服務壓力測試，主要目標是觀察在多個 Pod 共用同一張 GPU 的情境下，整體 service 的端到端延遲、server latency 與 GPU 資源使用變化。

本實驗目前採用 Kubernetes + NVIDIA device plugin GPU sharing 機制，透過 `nvidia.com/gpu.shared` 將同一張 GPU 切分成多個 shared slot，讓多個 YOLO inference Pod 可同時排程到同一個 GPU 節點上。

## 1. Project Structure

```text
experiments_yolo/
├── common/
│   ├── request_client_parallel.py
│   ├── task3_find_stable_window.py
│   ├── analyze_task3_stable_latency.py
│   ├── plot_task3_full_timeline.py
│   └── plot_resource_overview.py
├── saturation_multi_pod/
│   ├── find_focus_pod.sh
│   ├── run_task3_service_load_with_metrics.sh
│   └── yolo26_task3_saturation.yaml
├── configs/
├── debug/
└── results/
```

## 2. Experiment Goal

Task 3 的實驗目標是建立一個 GPU saturation scenario。

實驗中會在同一個 GPU 節點上部署多個 YOLO Pods，並透過一個 all-pods service 接收高併發 measurement traffic。

- all-pods service
  measurement client 會打到此 service，讓 request 分散到各個 Pod，用來量測較接近真實服務體感的 latency。
- GPU monitoring
  使用 `nvidia-smi` 每秒收集 GPU 資源資料，包含 GPU utilization、memory utilization、power draw、temperature。

此設計用來觀察：

- GPU 高負載下，整體 inference service 的延遲是否上升
- GPU utilization 是否真的達到 saturation
- GPU power / temperature 是否與 inference workload 呈現一致趨勢
- Kubernetes GPU shared slot 是否足以讓多個 Pod 同時排程到同一 GPU node

## 3. Kubernetes Task Design

### 3.1 Namespace

目前實驗使用 namespace：

`intent-lab`

### 3.2 Node

目前 Task 3 固定排程到 GPU node：

`icclz1`

Deployment 內會使用：

```yaml
nodeSelector:
  kubernetes.io/hostname: icclz1
```

### 3.3 GPU Resource

目前使用 NVIDIA device plugin 的 shared GPU resource：

`nvidia.com/gpu.shared: 1`

每個 YOLO Pod 會 request / limit 1 個 shared GPU slot。

範例：

```yaml
resources:
  limits:
    cpu: "2"
    memory: 6Gi
    nvidia.com/gpu.shared: "1"
  requests:
    cpu: "1"
    memory: 4Gi
    nvidia.com/gpu.shared: "1"
```

目前 `icclz1` 的 GPU shared slot 已調整為：

`nvidia.com/gpu.shared: 100`

檢查方式：

```bash
kubectl describe node icclz1 | sed -n '/Capacity:/,/Allocatable:/p' | grep -E "nvidia.com/gpu|nvidia.com/gpu.shared"
kubectl describe node icclz1 | sed -n '/Allocatable:/,/System Info:/p' | grep -E "nvidia.com/gpu|nvidia.com/gpu.shared"
```

預期可看到類似：

```text
nvidia.com/gpu.shared: 100
```

## 4. Program Description

### 4.1 `common/request_client_parallel.py`

平行 request client。

主要用途：

- 對指定 inference service 發送 HTTP request
- 支援 concurrency
- 支援 duration
- 支援 timeout
- 支援 repeat 參數
- 輸出每筆 request 的 latency 與 response metadata

輸出資料會包含：

```text
client_role
req_id
target_url
client_ts_start
client_ts_end
e2e_latency_ms
status_code
success
server_latency_ms
server_total_latency_ms
server_pod_name
server_node_name
server_service_role
model
device
imgsz
error_type
error_msg
```

### 4.2 `common/task3_find_stable_window.py`

用來從 GPU monitoring 資料中找出穩定負載區間。

目前 stable window 的判斷概念為：

- GPU utilization rolling mean >= threshold
- Power draw rolling mean >= threshold

例如：

```text
gpu_roll10 >= 80
power_roll10 >= 200
```

代表連續一段時間內 GPU utilization 與 power draw 都達到高負載水準。

輸出檔案：

`stable_windows.csv`

欄位包含：

```text
window_id,start_s,end_s,duration_s,gpu_mean,gpu_median,power_mean,power_median,temp_mean
```

### 4.3 `common/analyze_task3_stable_latency.py`

分析 stable window 內的 latency。

主要分析對象：

- `measurement_raw.csv`
- `stable_windows.csv`

可用來比較：

- service latency
- stable window 內的 e2e latency
- stable window 內的 server latency
- stable window 內的 server total latency
- 是否出現 timeout / error / abnormal spike

### 4.4 `common/plot_task3_full_timeline.py`

繪製完整時間軸的 latency 圖。

主要輸出：

- `fig1_full_time_e2e_latency.png`
- `fig2_full_time_e2e_latency_ma2.png`
- `fig3_full_time_server_latency.png`
- `fig4_full_time_server_latency_ma5.png`
- `fig5_full_time_server_total_latency.png`
- `fig6_full_time_server_total_latency_ma5.png`
- `fig7_full_time_overhead.png`
- `fig8_full_time_overhead_ma5.png`
- `fig9_full_time_gpu_utilization.png`

圖中會標示 stable window，但不會把 stable window 拆成多段圖，方便直接觀察完整實驗過程。

### 4.5 `common/plot_resource_overview.py`

繪製 GPU 資源統計圖。

主要輸入：

- `nvidia_smi_gpu_1s.csv`
- `stable_windows.csv`

主要輸出建議放在：

`results/saturation_multi_pod/<RUN_ID>/plots/`

輸出圖表：

- `gpu_resource_overview.png`
- `gpu_power_temp_dual_axis.png`
- `gpu_resource_normalized_trend.png`

其中目前主要使用：

`gpu_resource_overview.png`

此圖包含四個 GPU resource 指標：

- GPU Utilization
- GPU Memory Utilization
- GPU Power Draw
- GPU Temperature

## 4.6 Latency Definition

Task 3 目前主要會觀察三個核心 latency 指標：`e2e_latency_ms`、`server_latency_ms` 與 `server_total_latency_ms`。另外也會衍生一個輔助指標 `overhead_ms = e2e_latency_ms - server_total_latency_ms`，用來觀察 client、network 與平台路徑帶來的額外成本。

| 指標 | CSV 欄位 | 計算位置 / 來源程式 | 計算邏輯 | 涵蓋範圍 |
| --- | --- | --- | --- | --- |
| End-to-end latency | `e2e_latency_ms` | `common/request_client_parallel.py` | Client 端送 request 前記 `t0 = time.perf_counter()`，收到 response 或 exception 後記 `t1`，再算 `(t1 - t0) * 1000` | 從 client 發出請求到收到回應的完整往返時間，包含 client 本地讀圖 / 組 multipart request、網路傳輸、K8s Service routing、server 排隊 / 處理、response 回傳 |
| Server latency | `server_latency_ms` | YOLO server `/infer` API 回傳，client 只負責寫進 CSV | Server 端自己計算後放進 response JSON，`request_client_parallel.py` 讀取 `data.get("server_latency_ms")` | 主要代表 server 內部模型推論區段耗時。依目前 YOLO server 實作，較接近 `model.predict(...)` 的時間，不等於完整 HTTP handler 時間 |
| Server total latency | `server_total_latency_ms` | YOLO server `/infer` API 回傳，client 只負責寫進 CSV | Server 端從進入 `/infer` 一開始記錄 `handler_t0`，在 response return 前計算 `(time.perf_counter() - handler_t0) * 1000`，`request_client_parallel.py` 讀取 `data.get("server_total_latency_ms")` | 代表較完整的 server-side request handling latency，包含 `await file.read()`、`Image.open(...).convert("RGB")`、`model.predict(...)`、`torch.cuda.synchronize()` 後的模型處理區段，以及 response return 前的 server 端處理 |
| Overhead | `overhead_ms` | `common/analyze_task3_stable_latency.py`、`common/plot_task3_full_timeline.py` 內衍生計算 | `e2e_latency_ms - server_total_latency_ms` | 代表 server total latency 以外的額外成本總和，包含 client 本地讀圖 / 組 request、HTTP/TCP 開銷、網路傳輸、K8s Service routing、response 回傳與 client 端接收處理；不是純傳輸延遲 |

補充說明：

- `e2e_latency_ms` 不是由 `client_ts_end - client_ts_start` 直接相減得出，而是使用 `time.perf_counter()` 的差值計算。
- `client_ts_start` 與 `client_ts_end` 主要用於保存事件發生時間，方便和 GPU monitoring 或其他時間序列資料對齊。
- `server_latency_ms` 不是 `request_client_parallel.py` 自己算的，而是從 YOLO server 的 response JSON 中讀出後寫入 `measurement_raw.csv`。
- `server_total_latency_ms` 同樣不是 `request_client_parallel.py` 自己算的，而是由 YOLO server 計算後隨 response JSON 回傳，再由 client 寫入 CSV。
- `overhead_ms` 不是純 network latency，而是 `e2e_latency_ms` 扣掉 `server_total_latency_ms` 後的剩餘成本，因此更適合解讀成 client + network + platform overhead。

## 5. `saturation_multi_pod` Scripts

### 5.1 `saturation_multi_pod/find_focus_pod.sh`

用來快速查看目前 focus Pod 的 IP 與所在節點。

```bash
./saturation_multi_pod/find_focus_pod.sh
```

### 5.2 `saturation_multi_pod/run_task3_service_load_with_metrics.sh`

Task 3 主要執行腳本之一。

功能包含：

- 檢查 Task 3 Pods 是否正常 Running
- 啟動 GPU monitoring
- 啟動高併發 measurement client
- 收集 raw latency data
- 收集 `nvidia-smi` GPU resource data
- 自動偵測 stable window
- 自動執行 stable latency analysis
- 自動產生 timeline / resource plots
- 輸出結果到 `results/saturation_multi_pod/<RUN_ID>/`

執行範例：

```bash
cd /home/iccls2/AutoScale/experiments/experiments_yolo

DURATION=300 \
MEAS_CONCURRENCY=24 \
REPEAT=10 \
TIMEOUT_SEC=60 \
MEAS_SVC_NAME=yolo26n-task3 \
EXPECTED_PODS=6 \
./saturation_multi_pod/run_task3_service_load_with_metrics.sh
```

參數說明：

| 參數 | 說明 |
| --- | --- |
| `DURATION` | 實驗執行時間，單位秒 |
| `MEAS_CONCURRENCY` | measurement client 併發數；大於 1 時會進入高併發 service 壓測模式 |
| `REPEAT` | 每次 inference request 的 repeat 次數 |
| `TIMEOUT_SEC` | HTTP request timeout |
| `MEAS_SVC_NAME` | measurement 使用的 all-pods service 名稱 |
| `EXPECTED_PODS` | 預期 Running 的 Pod 總數 |

### 5.3 `saturation_multi_pod/yolo26_task3_saturation.yaml`

Task 3 主要 workload 設定。

通常包含：

- focus Deployment
- background Deployment（現作為 shared-load Pod pool）
- resource request / limit
- nodeSelector
- YOLO model 設定
- GPU device 設定

目前主要環境變數範例：

```text
YOLO26_SERVICE_ROLE: background
YOLO_MODEL: yolo26m.pt
YOLO26_MODEL: yolo26m.pt
YOLO26_DEVICE: cuda:0
YOLO_IMGSZ: 640
YOLO26_IMGSZ: 640
```

### 5.4 `yolo26n-task3` Service

all-pods Service，會選到本實驗中的 focus 與 background Pods。

設計目的：

- measurement traffic 打到 service 後可分散到各個 Pod
- 更接近真實服務對外提供時的 latency 體感
- 讓 `measurement_raw.csv` 反映 service routing 與多 Pod 分流後的整體延遲

檢查 service selector：

```bash
kubectl -n intent-lab get svc yolo26n-task3 -o yaml
```

## 6. Basic Usage

### 6.1 Apply Kubernetes YAML

```bash
cd /home/iccls2/AutoScale/experiments/experiments_yolo

kubectl apply -f saturation_multi_pod/yolo26_task3_saturation.yaml
```

### 6.2 Check Deployment

```bash
kubectl -n intent-lab get deploy yolo26n-task3-bg yolo26n-task3-focus
```

預期範例：

```text
NAME                  READY   UP-TO-DATE   AVAILABLE
yolo26n-task3-bg      5/5     5            5
yolo26n-task3-focus   1/1     1            1
```

### 6.3 Check Pods

```bash
kubectl -n intent-lab get pods -o wide -l app=yolo26n,exp=task3-saturation
```

預期所有 Pod 都應該在 `icclz1`，且狀態為 `Running`。

### 6.4 Scale Shared-Load Pods

例如將 shared-load Pods 調整為 5 個：

```bash
kubectl -n intent-lab scale deploy yolo26n-task3-bg --replicas=5
kubectl -n intent-lab rollout status deploy/yolo26n-task3-bg --timeout=180s
```

再次檢查：

```bash
kubectl -n intent-lab get pods -o wide -l app=yolo26n,exp=task3-saturation
```

### 6.5 Run Task 3 Experiment

```bash
cd /home/iccls2/AutoScale/experiments/experiments_yolo

DURATION=300 \
MEAS_CONCURRENCY=24 \
REPEAT=10 \
TIMEOUT_SEC=60 \
MEAS_SVC_NAME=yolo26n-task3 \
EXPECTED_PODS=6 \
./saturation_multi_pod/run_task3_service_load_with_metrics.sh
```

執行後會產生：

```text
results/saturation_multi_pod/task3_service_c24_repeat10_300s_<timestamp>/
```

## 7. Result Directory

每次實驗會產生一個獨立的 `RUN_DIR`。

範例：

```text
results/saturation_multi_pod/task3_service_c24_repeat10_300s_20260428_152033/
```

常見輸出檔案：

- `measurement_raw.csv`
- `nvidia_smi_gpu_1s.csv`
- `stable_windows.csv`
- `plots/`

建議圖表統一放在：

`results/saturation_multi_pod/<RUN_ID>/plots/`

## 8. Output Files

### 8.1 `measurement_raw.csv`

service-based 高併發量測結果。

主要用於分析：

- all-pods service 的 e2e latency
- all-pods service 下各 Pod 回應的 server latency
- all-pods service 下各 Pod 回應的 server total latency
- 高負載下整體服務體感是否受影響

重要欄位：

- `e2e_latency_ms`
- `server_latency_ms`
- `server_total_latency_ms`
- `server_pod_name`
- `server_node_name`
- `server_service_role`
- `success`
- `error_type`
- `error_msg`

### 8.2 `nvidia_smi_gpu_1s.csv`

每秒 GPU resource monitoring 結果。

主要欄位：

- `utilization.gpu [%]`
- `utilization.memory [%]`
- `power.draw [W]`
- `temperature.gpu`

### 8.3 `stable_windows.csv`

GPU stable high-load window 結果。

範例：

```text
window_id,start_s,end_s,duration_s,gpu_mean,gpu_median,power_mean,power_median,temp_mean
stable_1,43,95,53,90.28,93.00,230.00,239.74,67.13
stable_2,188,237,50,87.52,92.00,230.59,240.17,69.54
```

## 9. Manual Plot Commands

設定 `RUN_DIR`：

```bash
RUN_DIR=/home/iccls2/AutoScale/experiments/experiments_yolo/results/saturation_multi_pod/task3_service_c24_repeat10_300s_20260428_152033
```

### 9.1 Find Stable Windows

```bash
python3 common/task3_find_stable_window.py "$RUN_DIR"
```

注意：正式主腳本已自動執行這一步。

```bash
$RUN_DIR/stable_windows.csv
```

### 9.2 Plot Full Timeline

```bash
python3 common/plot_task3_full_timeline.py "$RUN_DIR"
```

建議輸出：

```text
$RUN_DIR/plots/fig1_full_time_e2e_latency.png
$RUN_DIR/plots/fig2_full_time_e2e_latency_ma2.png
$RUN_DIR/plots/fig3_full_time_server_latency.png
$RUN_DIR/plots/fig4_full_time_server_latency_ma5.png
$RUN_DIR/plots/fig5_full_time_server_total_latency.png
$RUN_DIR/plots/fig6_full_time_server_total_latency_ma5.png
$RUN_DIR/plots/fig7_full_time_overhead.png
$RUN_DIR/plots/fig8_full_time_overhead_ma5.png
$RUN_DIR/plots/fig9_full_time_gpu_utilization.png
```

### 9.3 Plot GPU Resource Overview

```bash
python3 common/plot_resource_overview.py "$RUN_DIR"
```

目前主要報告建議使用：

```text
$RUN_DIR/plots/gpu_resource_overview.png
```
