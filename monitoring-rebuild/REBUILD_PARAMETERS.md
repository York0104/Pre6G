# Rebuild Parameters

## Purpose

這份文件整理正式節點重建前最常需要替換的參數，避免直接在多個 YAML 與 script 中手動搜尋舊 IP/port。

## Primary Parameters

| Parameter | Current test value | Meaning | Where used |
| --- | --- | --- | --- |
| `CONTROL_PLANE_IP` | `140.113.179.9` | 中央監控與 API 對外可達入口 | host env、`vmagent-node-local` cadvisor proxy、Netdata child stream、API/dashboard |
| `VM_NODEPORT` | `31888` | VictoriaMetrics NodePort | host env、autoscale API、host-side `vm_aggregator` |
| `NETDATA_NODEPORT` | `32163` | Netdata parent NodePort | host env、autoscale API、Netdata child stream |
| `MONITORING_NS` | `monitoring` | 監控 namespace | `run_vm_aggregator_once.sh`、in-cluster job |
| `QUERY_NS` | `intent-lab` | 預設 workload 查詢 namespace | `vm_aggregator.py`、in-cluster job |
| `GPU_NODE_LABEL` | `feature.node.kubernetes.io/pci-10de.present=true` | GPU node selector | `dcgm-exporter`, `nvidia-device-plugin` |
| `NFD_GPU_ALIAS_RULE` | `monitoring-rebuild/71-nfd-gpu-alias-rule.yaml` | Map upstream NFD PCI labels back to bundle-style `pci-10de.present` | `nvidia-device-plugin`, `dcgm-exporter` |
| `NETDATA_STACK_MANIFEST` | `monitoring-rebuild/55-netdata.yaml` | Current Netdata parent/child/k8s-state stack manifest | Netdata rebuild |
| `NETDATA_CHILD_OVERRIDE` | `monitoring-rebuild/60-netdata-child-stream-config.yaml` | Current working Netdata child stream override | Netdata child stream to parent |

## Runtime Profiles

### Host-side profile

Use:

- [autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example)

適用於：

- `run_vm_aggregator_once.sh`
- `autoscale-api.service`
- 任何在 host shell / systemd 上執行的 collector 或 API

### In-cluster profile

Use:

- [autoscale-source-split/01-monitoring-layer/monitoring-runtime.incluster.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/monitoring-runtime.incluster.env.example)

適用於：

- `vm-aggregator-job.incluster.yaml`
- 任何直接跑在 cluster 內的 Pod / Job

## Files To Recheck Before Formal Rebuild

- [monitoring-rebuild/10-victoria-metrics.yaml](/home/icclz2/Pre6G/monitoring-rebuild/10-victoria-metrics.yaml)
- [monitoring-rebuild/20-vmagent.yaml](/home/icclz2/Pre6G/monitoring-rebuild/20-vmagent.yaml)
- [monitoring-rebuild/45-nvidia-device-plugin.yaml](/home/icclz2/Pre6G/monitoring-rebuild/45-nvidia-device-plugin.yaml)
- [monitoring-rebuild/55-netdata.yaml](/home/icclz2/Pre6G/monitoring-rebuild/55-netdata.yaml)
- [monitoring-rebuild/60-netdata-child-stream-config.yaml](/home/icclz2/Pre6G/monitoring-rebuild/60-netdata-child-stream-config.yaml)
- [monitoring-rebuild/71-nfd-gpu-alias-rule.yaml](/home/icclz2/Pre6G/monitoring-rebuild/71-nfd-gpu-alias-rule.yaml)
- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example)

## Current Notes

- `vmagent-node-local` 的 cadvisor proxy 與 remote write 仍直接用 `CONTROL_PLANE_IP` / NodePort，所以正式節點切換時一定要一起改。
- `45-nvidia-device-plugin.yaml` 依賴 GPU worker 主機上已正確配置 NVIDIA runtime，且 `k3s` 已自動提供 `RuntimeClass nvidia`。
- `55-netdata.yaml` 是目前 live `k3s` 環境抽出的完整 Netdata stack；`60-netdata-child-stream-config.yaml` 必須在它之後再套一次，確保 child stream 目的地是已驗證可用的 NodePort。
- host-side `vm_aggregator` 與 autoscale API 建議共用同一組 host env，避免兩邊端點不一致。
- in-cluster `vm_aggregator` 建議優先走 service DNS，不依賴 NodePort。
