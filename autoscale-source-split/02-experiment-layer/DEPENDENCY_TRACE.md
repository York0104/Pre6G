# Experiment Layer Dependency Trace

本文件確認 `02-experiment-layer/experiments_yolo/` 是否依賴較舊的 AutoScale 實驗資料夾，並說明 fan control、background load 與目前 k3s 重現前提。

## 結論

目前 `experiments_yolo/` 的 active code path 不再依賴：

```text
experiments/load_injection/
experiments/model_load/
experiments/monitoring/
```

唯一還提到舊路徑的地方，已只保留在歷史說明，不再是目前執行入口。

## Fan Control 來源

fan control 不是來自舊的 `experiments/load_injection/`。

目前是由 master 端腳本透過 SSH 啟動 worker：

```text
WORKER_HOST=140.113.179.6
WORKER_USER=icclz1
WORKER_SSH=icclz1-gpu
WORKER_REPO=/home/icclz1/gpu-tempctl-lab
```

主要入口：

```text
experiments_yolo/common/run_thermal_cycle_from_master.sh
experiments_yolo/common/run_bgload_fan_cycle_from_master.sh
```

worker 端必要專案：

```text
/home/icclz1/gpu-tempctl-lab/fan_control_lab/
```

重要 worker-side 檔案：

```text
fan_control_lab/cc.py
fan_control_lab/gpu_cycle_runner.py
fan_control_lab/gpu_supervisor_80.py
```

這些 worker-side 檔案不在本 repo 內；請搭配 `current-lab-handoff-private/` 與 worker 主機現場內容交付。

## YOLO service image 來源

YOLO service workload 目前依賴下列本地 image tag：

```text
local/yolo26n:0.1
local/yolo26n:0.1
```

目前 repo 內已提供可重建 image 的來源：

```text
02-experiment-layer/yolo26_workload/Dockerfile
02-experiment-layer/yolo26_workload/app.py
02-experiment-layer/yolo26_workload/build_and_import_image_to_k3s.sh
```

在新 k3s 環境中，不需要回頭找舊 image tar；直接 build / import 即可。但若 pod 會排到特定 GPU worker，該 worker 的 k3s/containerd 也必須有同一份 image。

## Background Load 來源

### YOLO service load

YOLO service load 由 k3s YOLO pods 與本層 request client 產生：

```text
experiments_yolo/saturation_multi_pod/yolo26_task3_saturation.yaml
experiments_yolo/saturation_multi_pod/run_task3_service_load_with_metrics.sh
experiments_yolo/common/request_client_parallel.py
experiments_yolo/common/request_client_serial.py
```

### Worker GPU thermal/background load

worker GPU thermal/background load 由 worker 端 `gpu-tempctl-lab` 提供。`run_bgload_fan_cycle_from_master.sh` 會從 worker repo import：

```text
from fan_control_lab.gpu_supervisor_80 import read_gpu_metrics, start_workload, stop_process
```

因此 `start_workload(...)` 不在舊的 AutoScale `experiments/load_injection/`，而是必須從 worker 端 `gpu-tempctl-lab` 恢復。

## GPU sharing / saturation 依賴

多 pod saturation 與三實例 YOLO workload 依賴：

```text
nvidia.com/gpu.shared
```

目前 repo 已直接收錄 reference config：

```text
experiments_yolo/saturation_multi_pod/gpu-sharing-icclz1.yaml
```

目前 `icclz1` live 環境已驗證：

- `nvidia.com/gpu.shared: 4`
- 3 實例 hostPort stack 可正常運行
- task3 4-pod stack 可完成短版 service-load smoke test

若 cluster 尚未出現 `nvidia.com/gpu.shared`：

- `single_pod_serial`
- `single_pod_serial_fault_fan`
- `single_pod_bgload_fan_cycle`

仍可先做；但：

- `yolo26_3inst_icclz1.yaml`
- `yolo26_task3_saturation.yaml`

不能直接排程成功。

## pandas / analyzer 備註

目前主 runner 已調整為：

- summary 階段不再依賴 `pandas`
- analyzer / plotting 階段若缺 `pandas`，改為 non-blocking，不會讓 smoke test 失敗

因此 `pandas` 不再是重現這些 workflow 的必要前置；它只在完整分析或部份圖表輸出時有幫助。

## 保持排除

以下資料夾可繼續排除於目前重建主線：

```text
experiments/load_injection/
experiments/model_load/
experiments/monitoring/
```

它們屬於其他研究線或歷史實驗，不是目前 thermal YOLO workflow 的必要依賴。
