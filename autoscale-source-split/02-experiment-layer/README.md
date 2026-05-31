# 02 Experiment Layer

本層保存 thermal YOLO 實驗 workflow。它依賴 `01-monitoring-layer` 提供 metrics/API，但監控層不依賴本層。

## 目前環境狀態

截至 2026-05-28，`02-experiment-layer` 已對齊目前 k3s 環境：

- worker node: `icclz1`
- worker host/IP: `140.113.179.6`
- worker SSH alias: `icclz1-gpu`
- worker external repo: `/home/icclz1/gpu-tempctl-lab`
- VictoriaMetrics: `http://140.113.179.9:31888`
- Netdata: `http://140.113.179.9:32163`
- repo root: `/home/icclz2/Pre6G`
- Python venv: `/home/icclz2/Pre6G/iccl`

`icclz1` 目前已正常提供：

- `node-exporter`
- `vmagent-node-local`
- `Netdata child`
- `nvidia-device-plugin`
- `dcgm-exporter`
- `nvidia.com/gpu=1`
- `nvidia.com/gpu.shared=4`

## 已完成驗證

### 1. YOLO image 與三實例 shared-GPU service

目前正式支援並建議使用的 image tag：

- `local/yolo26n:0.1`

`intent-lab` 的歷史匯出快照仍可見 `0.5`，但目前 repo 的正式重建與驗證流程一律以 `0.1` 為準。

目前 `intent-lab` 中已可正常提供三個 service：

- `yolo26n-focus` -> `18081`
- `yolo26n-bg-1` -> `18082`
- `yolo26n-bg-2` -> `18083`

三個 `healthz` 已驗證可回 `200`。

### 2. Baseline single-pod / three-instance smoke test

2026-05-28 已完成短版 baseline smoke test：

- focus: `50/50` success，client mean `137.589 ms`，server mean `18.783 ms`
- bg-1: `25/25` success，client mean `181.229 ms`，server mean `22.813 ms`
- bg-2: `25/25` success，client mean `221.967 ms`，server mean `22.610 ms`

### 3. Task3 service-load smoke test

已完成短版 task3 service-load smoke test（暫時切到 `yolo26_task3_saturation.yaml` 的 4-pod topology 後驗證，再恢復回三實例 hostPort stack）：

- `rows=126`
- `success=126`
- `success_rate=100%`
- `client_mean_ms=320.685`
- `client_p95_ms=394.563`
- `server_mean_ms=24.344`
- `server_p95_ms=43.1`

### 4. single_pod_serial_fault_fan 短版 smoke test

已完成短版 smoke test（`TARGET_MODE=pod`、`FAULT_HOLD_SECONDS=10`）：

- `rows=89`
- `success rate=1.0`
- `e2e mean=113.141 ms`
- `server mean=17.566 ms`
- `server total mean=33.028 ms`

### 5. single_pod_bgload_fan_cycle 短版 smoke test

已完成短版 smoke test（`TARGET_MODE=pod`、`CYCLES=1`、短 cycle 參數）：

- `rows=259`
- `success rate=1.0`
- `e2e mean=125.969 ms`
- `server mean=33.926 ms`
- `server total mean=45.921 ms`

### 6. 測試結果清理

上述 smoke test 產生的暫存結果已在驗證後刪除。`experiments_yolo/results/single_pod_serial_fault_fan/` 與 `experiments_yolo/results/single_pod_bgload_fan_cycle/` 目前為空。

## 重現前提

### 1. YOLO image

若在新環境重建，先執行：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_workload
bash build_and_import_image_to_k3s.sh
```

主要 image tag：

- `local/yolo26n:0.1`

注意：若 workload 會排到 GPU worker，該 worker 的 k3s/containerd 也必須有相同 image。

### 2. GPU sharing

三實例 shared-GPU 與 task3 saturation 依賴：

- `nvidia.com/gpu.shared`

目前 `icclz1` 已完成 time-slicing，現場狀態為：

- `nvidia.com/gpu.shared: 4`
- `yolo26n-focus` / `yolo26n-bg-1` / `yolo26n-bg-2` 可在 `intent-lab` 正常 `Running`

本目錄已放入 reference config：

- `experiments_yolo/saturation_multi_pod/gpu-sharing-icclz1.yaml`

### 3. worker-side fan / background-load control

下列 worker 端 repo 與檔案必須存在：

```text
/home/icclz1/gpu-tempctl-lab/fan_control_lab/cc.py
/home/icclz1/gpu-tempctl-lab/fan_control_lab/gpu_cycle_runner.py
/home/icclz1/gpu-tempctl-lab/fan_control_lab/gpu_supervisor_80.py
```

目前 master 端預設透過 `ssh icclz1-gpu` 操作這些 worker-side 工具。

## 主要用途

- 部署 YOLO26 k3s workload
- 產生 inference traffic 並記錄 latency
- 透過 worker 端 `gpu-tempctl-lab` 控制 fan/thermal cycle
- 收集 `vm_aggregator.py` metrics，合併 latency、thermal phase 與 GPU/Node 指標
- 產生實驗 summary、dataset 與圖表

## 根目錄檔案與目錄

| 路徑 | 說明 |
| --- | --- |
| `DEPENDENCY_TRACE.md` | 說明本層不再依賴舊 `experiments/load_injection/`、`model_load/`、`monitoring/`，並追蹤 fan/load 來源。 |
| `experiments_yolo/` | 目前主要 YOLO 實驗 workflow，包含 saturation、single pod、fault fan、bgload fan cycle。 |
| `scripts/` | 較早期或通用的 YOLO26 thermal/rate sweep 腳本。 |
| `thermal_analysis/` | thermal YOLO 資料收集、合併、繪圖與 batch runner。 |
| `yolo26_workload/` | YOLO26 inference service Dockerfile、app、k8s manifests、image build/import helper。 |

## Analyzer / pandas 備註

目前 smoke test runner 已調整為：

- `summary.txt` 不再依賴 `pandas`
- optional analyzer / plotting 若缺 `pandas`，不會阻斷主流程完成

因此：

- 想驗證 workflow 是否能跑通時，不必先補 `pandas`
- 若要完整使用 `analyze_*.py` / 某些進階圖表，再另外於對應 Python 環境安裝 `pandas`
