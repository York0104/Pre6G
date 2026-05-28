# experiments_yolo

本目錄是 `02-experiment-layer` 的主要 YOLO 實驗入口，重點在：

- 用 k3s 上的 YOLO service 產生 request traffic
- 搭配 `icclz1` 上的 `gpu-tempctl-lab` 做 fan control / background GPU load
- 同步收集 `vm_aggregator`、`nvidia-smi`、`kubectl top` 與 thermal phase 資料

目前已對齊的環境為：

- worker node: `icclz1`
- worker IP: `140.113.179.6`
- worker SSH alias: `icclz1-gpu`
- worker repo: `/home/icclz1/gpu-tempctl-lab`
- VictoriaMetrics: `http://140.113.179.9:31888`
- Netdata: `http://140.113.179.9:32163`
- repo root: `/home/icclz2/Pre6G`
- Python venv: `/home/icclz2/Pre6G/iccl`

## 實驗場景

### 1. `single_pod_serial/`

場景：

- 只保留一個 focus YOLO pod
- 不跑 background service pod
- client 採 closed-loop serial request
- 觀察單 pod 穩定服務時的 latency / resource 基線

適合用途：

- 做 baseline
- 確認 image、service、monitoring、serial client 都正常

啟動：

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial/run_single_pod_serial_with_metrics.sh
```

短版 smoke test：

```bash
cd /home/icclz2/Pre6G
TARGET_MODE=pod DURATION=60 TIMEOUT_SEC=20 REPEAT=1 \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial/run_single_pod_serial_with_metrics.sh
```

### 2. `single_pod_serial_fault_fan/`

場景：

- 只保留一個 focus YOLO pod
- 不跑 background service pod
- client 採 serial request
- worker fan 固定在低速（預設 `5%`）
- 觀察低風扇下的溫度上升與 latency 變化

適合用途：

- 做單 pod fault-fan 熱退化觀察
- 看溫度上升是否影響 `e2e_latency_ms` / `server_latency_ms`

啟動：

```bash
cd /home/icclz2/Pre6G
CC_PASSWORD='your_coolercontrol_password' \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial_fault_fan/run_single_pod_serial_fault_fan.sh
```

短版 smoke test：

```bash
cd /home/icclz2/Pre6G
NODE_SSH=icclz1-gpu TARGET_MODE=pod TIMEOUT_SEC=20 REPEAT=1 \
WARMUP_SECONDS=0 NORMAL_HOLD_SECONDS=0 FAULT_HOLD_SECONDS=10 VM_AGG_INTERVAL=1.0 \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial_fault_fan/run_single_pod_serial_fault_fan.sh
```

### 3. `single_pod_bgload_fan_cycle/`

場景：

- 只保留一個 focus YOLO pod
- 不跑 background service pod
- client 採 serial request
- worker 端另外開 torch matrix background GPU load
- fan 在 `GPU_DEFAULT` 與低速 fault mode 間切換
- 包含 `normal_hold`、`fault_hold`、`recovery_wait`

適合用途：

- 看有背景 GPU load 時的 thermal cycle
- 觀察 fan 切換與恢復對 latency / resource / temperature 的影響

啟動：

```bash
cd /home/icclz2/Pre6G
CC_PASSWORD='your_coolercontrol_password' \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh
```

短版 smoke test：

```bash
cd /home/icclz2/Pre6G
NODE_SSH=icclz1-gpu TARGET_MODE=pod TIMEOUT_SEC=20 REPEAT=1 \
CYCLES=1 NORMAL_HOLD_SECONDS=5 FAULT_HOLD_SECONDS=5 \
RECOVERY_STABLE_SECONDS=5 RECOVERY_MAX_SECONDS=20 WORKLOAD_HEADROOM_SECONDS=10 \
VM_AGG_INTERVAL=1.0 \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh
```

`run_single_pod_bgload_fan_cycle_loop.sh` 則是把上述單次實驗用 `CYCLES=1` 的方式反覆重跑，適合批次累積多個 run。

### 4. `saturation_multi_pod/`

場景：

- 使用 `nvidia.com/gpu.shared`
- 在 `icclz1` 上同時跑多個 YOLO pod
- 對應 task3 / shared-GPU service-load 實驗

目前已驗證：

- `icclz1` 已有 `nvidia.com/gpu.shared: 4`
- `yolo26_task3_saturation.yaml` 對應的 4-pod stack 可正常建立
- `run_task3_service_load_with_metrics.sh` 已完成短版 smoke test

啟動：

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/02-experiment-layer/experiments_yolo/saturation_multi_pod/run_task3_service_load_with_metrics.sh
```

若要先確認 GPU sharing：

```bash
kubectl describe node icclz1 | grep -E 'nvidia.com/gpu|nvidia.com/gpu.shared'
```

## 執行前共同前提

### 1. 先 build / import YOLO image

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_k8s
bash build_and_import_image_to_k3s.sh
```

主要 image tag：

- `local/yolo26n:0.1`
- `local/yolo26n:0.5`

注意：若 pod 會排到 GPU worker，該 worker 的 k3s/containerd 也必須有相同 image。

### 2. 確認 worker SSH 可用

```bash
ssh icclz1-gpu "echo ok"
```

### 3. 若會跑 fan-cycle 類實驗，確認 worker-side repo 在

```bash
ssh icclz1-gpu "ls /home/icclz1/gpu-tempctl-lab/fan_control_lab"
```

## 子目錄說明

- `common/`
  - 共用 request client、thermal runner、summary / plot helper
- `single_pod_serial/`
  - 單 pod serial baseline
- `single_pod_serial_fault_fan/`
  - 單 pod + 低風扇 fault 模式
- `single_pod_bgload_fan_cycle/`
  - 單 pod + background GPU load + fan cycle
- `saturation_multi_pod/`
  - shared-GPU / task3 類多 pod service-load
- `yolo_demo/`
  - 展示/輔助用途，不是目前主驗證線

## 備註

- 目前 smoke test runner 的 `summary.txt` 已不再硬依賴 `pandas`
- 某些 `analyze_*.py` / `plot_*.py` 若缺 `pandas`，現在會是 non-blocking，不影響主流程驗證
- `single_pod_*` 類 workflow 在執行期間會暫時把 `yolo26n-bg-1` scale 到 `0`
  - 驗證結束後應恢復原本三實例 layout
