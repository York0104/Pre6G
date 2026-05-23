# Experiment Layer Dependency Trace

本文件確認 `02-experiment-layer/experiments_yolo/` 是否依賴 AutoScale 中較舊的實驗資料夾，並說明 fan control 與 background load 的實際來源。

## 結論

目前 `experiments_yolo/` 的 active code path 沒有呼叫：

```text
experiments/load_injection/
experiments/model_load/
experiments/monitoring/
```

唯一出現 `experiments/monitoring` 的地方是 `scripts/README_yolo26_3inst.md` 的舊路徑提醒，內容是提醒不要使用舊路徑。

## Fan Control 來源

fan control 不是來自 AutoScale 的 `experiments/load_injection/`。

目前是由 master 端腳本透過 SSH 啟動 worker：

```text
WORKER_HOST=100.105.48.97
WORKER_USER=icclz1
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

這些 worker-side 檔案不在本機交接包內；請參考 `k3s-migration-bundle-sanitized/external-worker/`。

## Background Load 來源

### YOLO service load

YOLO service load 由 k8s YOLO pods 與本層 request client 產生：

```text
experiments_yolo/saturation_multi_pod/yolo26_task3_saturation.yaml
experiments_yolo/saturation_multi_pod/run_task3_service_load_with_metrics.sh
experiments_yolo/common/request_client_parallel.py
experiments_yolo/common/request_client_serial.py
```

`yolo26_task3_saturation.yaml` 會建立：

```text
yolo26n-task3-focus
yolo26n-task3-bg
```

兩者皆使用：

```text
local/yolo26n:0.5
```

### Worker GPU thermal/background load

worker GPU thermal/background load 由 worker 端 `gpu-tempctl-lab` 提供。`run_bgload_fan_cycle_from_master.sh` 會從 worker repo import：

```text
from fan_control_lab.gpu_supervisor_80 import read_gpu_metrics, start_workload, stop_process
```

因此 `start_workload(...)` 不在 AutoScale 的 `experiments/load_injection/`，而是必須從 worker 端 `gpu-tempctl-lab` 恢復。

## 保持排除

以下資料夾可繼續排除於目前交接 source split：

```text
experiments/load_injection/
experiments/model_load/
experiments/monitoring/
```

它們屬於其他研究線或歷史實驗，不是目前 thermal YOLO workflow 的必要依賴。
