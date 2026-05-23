# AutoScale File Groups

本文件將 `/home/iccls2/AutoScale` 重要檔案依交接角色分組。實際已整理出的 source split 位於：

```text
../../autoscale-source-split/
```

## Monitoring / Observability

| 路徑 | 說明 |
| --- | --- |
| `vm_aggregator.py` | 目前主要 K8s/GPU node aggregator。 |
| `vm_agg_rfsoc.py` | RFSoC 外部節點 aggregator。 |
| `vm_agg_ap_gateway.py` | AP/OpenWrt gateway aggregator。 |
| `netdata_client.py` | Netdata API helper。 |
| `collector_nodes.json` | aggregator target/node 設定。 |
| `collect_full_metrics_api_csv.py` | 收集 full metrics API CSV。 |
| `collect_node_metrics_csv.py` | 收集單一 node metrics CSV。 |
| `run_full_metrics_api_collector.sh` | full metrics collector wrapper。 |
| `run_vm_aggregator_once.sh` | aggregator smoke helper。 |
| `ap_gateway/` | AP gateway 與 SNMP gateway。 |
| `k8s-expose/` | Netdata / VictoriaMetrics NodePort manifests。 |
| `netdata-default-values.yaml` | Netdata Helm values 參考。 |
| `vm-aggregator-job.incluster.yaml` | cluster 內 aggregator Job 參考。 |
| `systemd/` | AutoScale API service/env template。 |
| `docs/full-metrics-handoff.md` | full metrics API 交接說明。 |
| `docs/frontend-api-handoff.md` | 前端/API 對接說明。 |
| `docs/vm-aggregators-reference.md` | aggregator 欄位與 schema 參考。 |

## Thermal / YOLO Experiments

| 路徑 | 說明 |
| --- | --- |
| `experiments/yolo26_k8s/` | YOLO26 app、Dockerfile、k8s manifests。 |
| `experiments/thermal_analysis/` | thermal/latency/VM metrics 合併與繪圖工具。 |
| `experiments/experiments_yolo/common/` | 共用 request clients、plot/analyze scripts、worker cycle wrappers。 |
| `experiments/experiments_yolo/saturation_multi_pod/` | 多 pod saturation 實驗。 |
| `experiments/experiments_yolo/single_pod_bgload_fan_cycle/` | 單 pod 搭配 background GPU load/fan cycle。 |
| `experiments/experiments_yolo/single_pod_serial/` | 單 pod serial latency 量測。 |
| `experiments/experiments_yolo/single_pod_serial_fault_fan/` | 單 pod 固定低風扇/fault fan 實驗。 |
| `scripts/run_A_normal_baseline_yolo.sh` | baseline runner。 |
| `scripts/run_B_thermal_yolo26_3inst.sh` | thermal YOLO runner。 |
| `scripts/run_C_thermal_yolo26_3inst_cycles.sh` | thermal YOLO multi-cycle runner。 |
| `scripts/run_yolo26_singlepod_*rate_sweep.sh` | rate sweep runners。 |

## API / Dashboard Shared Surface

| 路徑 | 說明 |
| --- | --- |
| `autoscale_api/` | FastAPI backend；同時含 monitoring 與 experiment-control API。 |
| `cluster-dashboard/` | 前端 dashboard source。 |
| `systemd/autoscale-api.service` | API systemd service template。 |
| `systemd/autoscale-api.env.example` | API env 範例。 |

## Low-Priority / Historical

以下不屬於目前 k3s monitoring + thermal YOLO 交接主線，除非需要歷史重現，否則不建議納入：

```text
source/
data/workload_v2.py
data/workload_v2_RL.py
experiments/load_injection/
experiments/model_load/
experiments/monitoring/plot_cluster_cpu_utilization.py
report.md
report.dd
hello-deploy.yaml
test.py
utils/test.py
source/test.py
```

## 不應納入交接包

```text
cluster-dashboard/node_modules/
iccl/
iccl_torch_old/
experiments/experiments_yolo/results/
__pycache__/
tools/cloudflared
```

原因：安裝產物、virtualenv、歷史輸出、cache 或本機 binary。
