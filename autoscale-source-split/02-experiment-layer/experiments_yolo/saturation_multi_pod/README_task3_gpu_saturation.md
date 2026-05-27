# Task3 GPU Saturation

本實驗在目前 k3s 環境下仍可重建，但有兩個前置條件：

1. 先匯入 YOLO image
2. 先啟用 `nvidia.com/gpu.shared`

## 前置條件

### 匯入 YOLO image

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_k8s
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
