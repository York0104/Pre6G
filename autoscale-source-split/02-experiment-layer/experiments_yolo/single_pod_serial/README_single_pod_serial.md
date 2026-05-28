# experiments_yolo: Single Pod Serial Service Experiment

本資料夾用於設計與執行單一 YOLO Pod 的 closed-loop serial request 實驗。

此實驗與 `saturation_multi_pod/` 的差異在於：

- 只保留一個 focus YOLO serving pod
- 不使用 concurrency 壓測
- client 僅在前一個 request 完成後，才送出下一個 request
- 觀察重點改為長時間 serial serving 下的 latency、throughput 與 GPU thermal/resource trend

## 目前環境對齊

目前已對齊：

- repo root: `/home/icclz2/Pre6G`
- Python venv: `/home/icclz2/Pre6G/iccl`
- worker IP: `140.113.179.6`
- worker SSH alias: `icclz1-gpu`
- worker node: `icclz1`
- namespace: `intent-lab`
- focus deploy: `yolo26n-focus`
- background deploys: `yolo26n-bg-1` / `yolo26n-bg-2`

## 已驗證狀態

2026-05-28 已完成 baseline smoke test：

- focus: `50/50` success，client mean `137.589 ms`，server mean `18.783 ms`
- bg-1: `25/25` success，client mean `181.229 ms`，server mean `22.813 ms`
- bg-2: `25/25` success，client mean `221.967 ms`，server mean `22.610 ms`

測試輸出已於驗證後刪除。

## Main Scripts

### `common/request_client_serial.py`

單一 serial client。

特性：

- 每次只保留一個 in-flight request
- 上一筆完成後才送下一筆
- 輸出欄位盡量和 `request_client_parallel.py` 保持一致
- 額外增加：
  - `inter_request_gap_ms`
  - `loop_elapsed_ms`

### `single_pod_serial/run_single_pod_serial_with_metrics.sh`

此腳本會：

1. scale `yolo26n-focus` 到 `1`
2. scale `yolo26n-bg-1` / `yolo26n-bg-2` 到 `0`
3. 蒐集 pod / deployment / event 狀態
4. 啟動 `nvidia-smi` 與 `kubectl top` 監控
5. 啟動 serial request client
6. 產生 `summary.txt`、`serial_analysis.txt`、`plots/`

## How To Run

### Basic Run

```bash
cd /home/icclz2/Pre6G
autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial/run_single_pod_serial_with_metrics.sh
```

### Example: 5-Minute Run

```bash
cd /home/icclz2/Pre6G
DURATION=300 TIMEOUT_SEC=30 REPEAT=10 bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial/run_single_pod_serial_with_metrics.sh
```

### Example: Force Pod Mode

```bash
cd /home/icclz2/Pre6G
TARGET_MODE=pod DURATION=300 TIMEOUT_SEC=30 REPEAT=10 bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial/run_single_pod_serial_with_metrics.sh
```

## Common Environment Variables

- `DURATION`
- `TIMEOUT_SEC`
- `REPEAT`
- `TARGET_MODE`
  - `service` 或 `pod`
- `NAMESPACE`
  - 預設 `intent-lab`
- `NODE_SSH`
  - 預設 `icclz1-gpu`
- `WORKER_IP`
  - 預設 `140.113.179.6`

## Outputs

結果會寫到：

```text
autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_serial/<RUN_ID>/
```

建議優先查看：

- `experiment_config.txt`
- `summary.txt`
- `serial_analysis.txt`
- `measurement_raw.csv`
- `nvidia_smi_gpu_1s.csv`
- `plots/`

## Notes

- 目前 runner 的 summary 階段已不再依賴 `pandas`
- 若額外 analyzer / plotter 需要 `pandas`，缺少時不影響 smoke test 主流程完成
