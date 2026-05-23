# Monitoring / Experiment Separation

本文件定義目前交接包的責任邊界。重建時應先恢復 monitoring layer，再啟動 thermal YOLO experiment layer。

## Layer A：Monitoring / Observability

職責：

- 收集 host、Kubernetes、container、GPU、AP、RFSoC metrics。
- 透過 VictoriaMetrics 儲存與查詢 time series。
- 由 AutoScale aggregators/API 提供彙整狀態。
- 提供 NodePort 或 service endpoint 供外部驗證。

主要元件：

```text
VictoriaMetrics
vmagent
node-exporter
kube-state-metrics
kubelet/cAdvisor
dcgm-exporter
Netdata
NVIDIA Device Plugin / GPU sharing
RFSoC node-exporter scrape
OpenWrt AP SNMP / AP gateway
AutoScale aggregators
AutoScale API full-metrics endpoints
```

主要 source/config：

```text
autoscale-source-split/01-monitoring-layer/
k3s-migration-bundle-sanitized/monitoring/
k3s-migration-bundle-sanitized/gpu/
k3s-migration-bundle-sanitized/nvidia-device-plugin/
k3s-migration-bundle-sanitized/netdata-ap/
k3s-migration-bundle-sanitized/rfsoc/
k3s-migration-bundle-sanitized/cluster-access/
```

## Layer B：Thermal YOLO Experiments

職責：

- 部署 YOLO service/workload。
- 產生 request traffic 並記錄 latency。
- 透過 worker-side `gpu-tempctl-lab` 協調 fan/thermal cycle。
- 從 monitoring layer 收集 snapshots/time series。
- 合併 latency、thermal phase 與 VM aggregator metrics，產生 dataset/plot/summary。

主要 source/config：

```text
autoscale-source-split/02-experiment-layer/
k3s-migration-bundle-sanitized/thermal-yolo/
k3s-migration-bundle-sanitized/external-worker/
```

## 允許依賴

唯一應存在的硬依賴方向：

```text
experiment runner -> monitoring metrics/API
```

合理範例：

- experiment scripts 透過 `collect_vm_aggregator_csv.py` 呼叫 `vm_aggregator.py`。
- experiment scripts 查詢 VictoriaMetrics、Netdata、DCGM metrics。
- experiment scripts 使用 `kubectl` 讀取 workload 狀態。

## 不應存在的依賴

```text
vmagent / VictoriaMetrics / Netdata / DCGM -> experiment runner
aggregator core -> thermal run scripts
RFSoC/AP monitoring -> YOLO workload
```

目前 audit 未發現 monitoring deployment config 需要依賴 experiment runner。

## AutoScale API 的定位

AutoScale API 同時包含 monitoring 與 experiment-control：

| 類型 | 代表檔案 |
| --- | --- |
| Monitoring API | `routers/full_metrics.py`、`services/full_metrics_service.py`、`routers/nodes.py` |
| Experiment-control API | `routers/experiments.py`、`services/fan_cycle_experiment_service.py`、`services/yolo_demo_service.py` |

因此 source split 將 API/dashboard 獨立為：

```text
autoscale-source-split/03-shared-api-dashboard/
```

## 建議重建順序

1. 重建 k3s/GPU runtime。
2. 安裝 NVIDIA Device Plugin/GPU sharing。
3. 安裝 VictoriaMetrics、vmagent、node-exporter、kube-state-metrics、dcgm-exporter、Netdata。
4. 恢復 AP/RFSoC monitoring access。
5. 啟動 AutoScale API/aggregators。
6. 驗證 metrics。
7. build/import YOLO image。
8. 套用 YOLO workloads。
9. 恢復 worker-side fan-control。
10. 執行 thermal experiments。

## 實驗前驗證

```bash
kubectl -n monitoring get pods
kubectl -n gpu-monitoring get pods
kubectl -n netdata get pods
kubectl -n nvidia-device-plugin get pods
```

```bash
curl 'http://<victoria-metrics-url>/api/v1/query?query=node_cpu_seconds_total'
curl 'http://<victoria-metrics-url>/api/v1/query?query=container_cpu_usage_seconds_total'
curl 'http://<victoria-metrics-url>/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP'
```

```bash
python3 vm_aggregator.py
python3 vm_agg_rfsoc.py
python3 vm_agg_ap_gateway.py
```
