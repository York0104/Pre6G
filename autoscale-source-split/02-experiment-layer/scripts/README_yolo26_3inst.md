# YOLO26 3-Instance Thermal Experiment README

本文件說明 `scripts/run_B_thermal_yolo26_3inst.sh` 與 `scripts/run_C_thermal_yolo26_3inst_cycles.sh` 在目前 k3s 環境中的用途、依賴與重現前提。

## 目前環境對齊

目前已對齊的新環境為：

- worker node: `icclz1`
- worker IP: `140.113.179.6`
- worker SSH alias: `icclz1-gpu`
- worker repo: `/home/icclz1/gpu-tempctl-lab`
- monitoring VM URL: `http://140.113.179.9:31888`
- monitoring Netdata URL: `http://140.113.179.9:32163`
- repo root: `/home/icclz2/Pre6G`
- Python venv: `/home/icclz2/Pre6G/iccl`

## 目前已驗證的基底

截至 2026-05-28，下列基底已驗證成功：

- `icclz1` 具有 `nvidia.com/gpu.shared: 4`
- 三實例 YOLO hostPort service 已可正常提供
  - `yolo26n-focus` -> `18081`
  - `yolo26n-bg-1` -> `18082`
  - `yolo26n-bg-2` -> `18083`
- `task3` 4-pod saturation stack 可完成短版 service-load smoke test
- `single_pod_serial_fault_fan` 短版 smoke test 已完成
- `single_pod_bgload_fan_cycle` 短版 smoke test 已完成

因此目前阻力不在 k3s / GPU sharing / SSH，而主要在於：

- 你要跑多長的正式實驗時間
- 是否需要完整 analyzer / plotting（這些部份可能還要安裝 `pandas`）

## 核心前提

### 1. YOLO image 必須先匯入 k3s

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_k8s
bash build_and_import_image_to_k3s.sh
```

此步會建立並匯入：

- `local/yolo26n:0.1`
- `local/yolo26n:0.5`

若 workload 會排到 GPU worker，請確認該 worker 的 k3s/containerd 也有相同 image。

### 2. 三實例與 task3 saturation 仍需要 GPU sharing

三實例與 task3 saturation 使用：

```yaml
nvidia.com/gpu.shared: "1"
```

若目前 cluster 尚未出現 `nvidia.com/gpu.shared`，請先比對或套用：

- `../experiments_yolo/saturation_multi_pod/gpu-sharing-icclz1.yaml`
- `../../../k3s-migration-bundle-sanitized/nvidia-device-plugin/`

### 3. worker-side fan control 仍依賴外部 repo

以下檔案必須存在於 worker：

```text
/home/icclz1/gpu-tempctl-lab/fan_control_lab/cc.py
/home/icclz1/gpu-tempctl-lab/fan_control_lab/gpu_cycle_runner.py
/home/icclz1/gpu-tempctl-lab/fan_control_lab/gpu_supervisor_80.py
```

## 執行順序

### 單次三實例 thermal run

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/02-experiment-layer/scripts/run_B_thermal_yolo26_3inst.sh
```

### 多 cycle thermal run

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/02-experiment-layer/scripts/run_C_thermal_yolo26_3inst_cycles.sh
```

## 若目前只想先驗證核心鏈路

可先跑已驗證完成的短版主線：

- `experiments_yolo/single_pod_serial/`
- `experiments_yolo/single_pod_serial_fault_fan/`
- `experiments_yolo/single_pod_bgload_fan_cycle/`
- `experiments_yolo/saturation_multi_pod/run_task3_service_load_with_metrics.sh`

這些 workflow 已在目前環境完成 smoke test，且測試輸出已證實可以在驗證後刪除，不影響 live service 恢復。
