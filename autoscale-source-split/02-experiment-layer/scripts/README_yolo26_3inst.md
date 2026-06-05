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

截至 2026-06-02，下列基底已重新驗證成功：

- `icclz1` 具有 `nvidia.com/gpu.shared: 4`
- 三實例 YOLO hostPort service 已可正常提供
  - `yolo26n-focus` -> `18081`
  - `yolo26n-bg-1` -> `18082`
  - `yolo26n-bg-2` -> `18083`
- `task3` 4-pod saturation stack 可完成短版 service-load smoke test
- `single_pod_serial` 短版 smoke test 已重新完成
- `single_pod_serial_fault_fan` 短版 smoke test 已重新完成
- `single_pod_bgload_fan_cycle` 短版 smoke test 已重新完成
- `scripts/run_A_normal_baseline_yolo.sh` 短版 smoke test 已重新完成
  - focus `600/600` success，client mean `61.283 ms`，server mean `29.158 ms`
  - bg-1 `300/300` success，client mean `90.206 ms`，server mean `45.408 ms`
  - bg-2 `300/300` success，client mean `90.240 ms`，server mean `45.301 ms`
  - `health_fail_total=0`
  - `warmup_fail_total=0`

因此目前主要阻力已轉為：

- 正式實驗時長與排程安排
- 是否補 `pandas` 以取得完整 analyzer / plotting 輸出

## 核心前提

### 1. YOLO image 必須先匯入 k3s

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_workload
bash build_and_import_image_to_k3s.sh
```

此步目前正式支援並建議使用：

- `local/yolo26n:0.1`

歷史上曾出現 `0.5`，但這不再是目前建議的驗證或重建標準。

若 workload 會排到 GPU worker，請確認該 worker 的 k3s/containerd 也有相同 image。

補充：

- repo 內正式 canonical path 已統一為 `yolo26_workload/`
- `icclz1` 現場若仍保留 `~/yolo26_k8s`，可作為 legacy build source 用來 build/import `local/yolo26n:0.1`

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

可先跑已重新驗證完成的短版主線：

- `experiments_yolo/single_pod_serial/`
- `experiments_yolo/saturation_multi_pod/run_task3_service_load_with_metrics.sh`

`fault_fan` / `bgload_fan_cycle` 也已在本輪完成短版 smoke test。
