# Task3 GPU Saturation

本實驗在目前 k3s 環境下可重建，前提是：

1. YOLO image 已匯入 control-plane 與目標 GPU worker 的 k3s/containerd
2. `icclz1` 已啟用 `nvidia.com/gpu.shared`

## 目前已驗證狀態

截至 2026-05-28：

- `icclz1` 已出現 `nvidia.com/gpu.shared: 4`
- `yolo26_task3_saturation.yaml` 對應的 4-pod stack 可正常建立
  - `yolo26n-task3-focus`
  - `yolo26n-task3-bg` x3
- 短版 service-load smoke test 已完成
  - `rows=126`
  - `success=126`
  - `success_rate=100%`
  - `client_mean_ms=320.685`
  - `server_mean_ms=24.344`
- 驗證後已恢復原本三實例 hostPort stack
  - `yolo26n-focus`
  - `yolo26n-bg-1`
  - `yolo26n-bg-2`

2026-06-02 已於目前主機重新完成短版 service-load smoke test：

- `rows=3118`
- `success_rate=100%`
- `client_mean_ms=76.477`
- `client_p95_ms=121.749`
- `server_mean_ms=25.342`
- `server_p95_ms=38.564`
- 驗證後已恢復原本三實例 hostPort stack
- 測試輸出已於驗證後刪除

## 前置條件

### 匯入 YOLO image

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_workload
bash build_and_import_image_to_k3s.sh
```

### 啟用 GPU sharing

目前本目錄已收錄本機 reference config：

- `gpu-sharing-icclz1.yaml`

原始 bundle 參考仍在：

- `k3s-migration-bundle-sanitized/nvidia-device-plugin/`

請先確認 cluster 已出現：

```bash
kubectl describe node icclz1 | sed -n '/Capacity:/,/Allocatable:/p' | grep -E 'nvidia.com/gpu|nvidia.com/gpu.shared'
kubectl describe node icclz1 | sed -n '/Allocatable:/,/System Info:/p' | grep -E 'nvidia.com/gpu|nvidia.com/gpu.shared'
```

若沒有 `nvidia.com/gpu.shared`，則 `yolo26_task3_saturation.yaml` 不能直接排程。

## 執行

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/02-experiment-layer/experiments_yolo/saturation_multi_pod/run_task3_service_load_with_metrics.sh
```

## 備註

- 這條 workflow 的主線現在已可跑通
- 若要完整使用後處理 analyzer / advanced plots，仍可能需要在對應 Python 環境補 `pandas`
- smoke test 階段不再以 `pandas` 作為阻斷依賴
