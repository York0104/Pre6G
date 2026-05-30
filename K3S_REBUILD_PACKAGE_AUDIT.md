# K3S Rebuild Package Audit

Date: 2026-05-27
Scope: `Pre6G` 中目前可交付的 `monitor + Cluster Monitor dashboard` 重建主線，不含 `02-experiment-layer` 實驗驗收。

## Overall Assessment

目前可作為另一台 `k3s` 環境重建基底的主入口為：

1. [MONITORING_REBUILD_SOP.md](MONITORING_REBUILD_SOP.md)
2. [monitoring-rebuild/REBUILD_PARAMETERS.md](monitoring-rebuild/REBUILD_PARAMETERS.md)
3. [MONITORING_REBUILD_K3S_MIGRATION_NOTES.md](MONITORING_REBUILD_K3S_MIGRATION_NOTES.md)
4. [MONITORING_REBUILD_PROGRESS.md](MONITORING_REBUILD_PROGRESS.md)

目前監控與 `Cluster Monitor` dashboard 主線已接近可交付；已知剩餘風險主要是節點主機狀態，而非重建檔案缺漏。

## Required Files For Rebuild

### Core manifests

- [monitoring-rebuild/00-namespaces.yaml](monitoring-rebuild/00-namespaces.yaml)
- [monitoring-rebuild/10-victoria-metrics.yaml](monitoring-rebuild/10-victoria-metrics.yaml)
- [monitoring-rebuild/20-vmagent.yaml](monitoring-rebuild/20-vmagent.yaml)
- [monitoring-rebuild/30-node-exporter.yaml](monitoring-rebuild/30-node-exporter.yaml)
- [monitoring-rebuild/40-kube-state-metrics.yaml](monitoring-rebuild/40-kube-state-metrics.yaml)
- [monitoring-rebuild/45-nvidia-device-plugin.yaml](monitoring-rebuild/45-nvidia-device-plugin.yaml)
- [monitoring-rebuild/50-dcgm-exporter.yaml](monitoring-rebuild/50-dcgm-exporter.yaml)
- [monitoring-rebuild/55-netdata.yaml](monitoring-rebuild/55-netdata.yaml)
- [monitoring-rebuild/60-netdata-child-stream-config.yaml](monitoring-rebuild/60-netdata-child-stream-config.yaml)
- [monitoring-rebuild/70-node-feature-discovery.yaml](monitoring-rebuild/70-node-feature-discovery.yaml)
- [monitoring-rebuild/71-nfd-gpu-alias-rule.yaml](monitoring-rebuild/71-nfd-gpu-alias-rule.yaml)

### Runtime/query entrypoints

- [autoscale-source-split/01-monitoring-layer/run_vm_aggregator_once.sh](autoscale-source-split/01-monitoring-layer/run_vm_aggregator_once.sh)
- [autoscale-source-split/01-monitoring-layer/vm-aggregator-job.incluster.yaml](autoscale-source-split/01-monitoring-layer/vm-aggregator-job.incluster.yaml)
- [autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example](autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example)
- [autoscale-source-split/01-monitoring-layer/monitoring-runtime.incluster.env.example](autoscale-source-split/01-monitoring-layer/monitoring-runtime.incluster.env.example)
- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example](autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example)
- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service](autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service)

### API/dashboard start points

- [autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh](autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh)
- [autoscale-source-split/03-shared-api-dashboard/autoscale_api/README.md](autoscale-source-split/03-shared-api-dashboard/autoscale_api/README.md)
- [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh](autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh)
- [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/README.md](autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/README.md)

## Helpful But Not Stored As Manifests

這些對重建有幫助，但屬於主機或私密側資訊：

- `k3s` control-plane 的 kubeconfig
- `k3s` join token
- GPU worker 主機上的 NVIDIA driver / toolkit 狀態
- `RuntimeClass nvidia`
  - 目前由 `k3s` runtime addon 自動提供，沒有額外收錄為 repo manifest
- `current-lab-handoff-private/private-files-to-fill/` 內的私密檔案

## autoscale-source-split Doc Status

### `01-monitoring-layer`

狀態：已更新到目前 `k3s` 主線。

可直接用的文檔：
- [autoscale-source-split/01-monitoring-layer/README.md](autoscale-source-split/01-monitoring-layer/README.md)
- [autoscale-source-split/01-monitoring-layer/docs/api-dashboard-bootstrap.md](autoscale-source-split/01-monitoring-layer/docs/api-dashboard-bootstrap.md)
- [autoscale-source-split/01-monitoring-layer/docs/vm-aggregators-reference.md](autoscale-source-split/01-monitoring-layer/docs/vm-aggregators-reference.md)

### `02-experiment-layer`

狀態：未更新為目前 `k3s` 驗收主線；仍屬實驗層參考。

說明：
- 內容仍保留舊 worker 預設、舊路徑、舊 GPU 節點命名。
- 因本輪未完成 experiment workflow 驗收，這些文檔不應當作目前 `k3s` 主線交付入口；但必要 source/workload 已保留，可在下一台 `k3s` 環境接續完成。

### `03-shared-api-dashboard`

狀態：主線文檔已更新。

可直接用的文檔：
- [autoscale-source-split/03-shared-api-dashboard/README.md](autoscale-source-split/03-shared-api-dashboard/README.md)
- [autoscale-source-split/03-shared-api-dashboard/autoscale_api/README.md](autoscale-source-split/03-shared-api-dashboard/autoscale_api/README.md)
- [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/README.md](autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/README.md)

注意：
- `Cluster Monitor` 已驗證
- experiment-related API/services 仍保留，但不列入本次正式重建驗收

## Files Removed Or Already Replaced

這些舊內容已不再作為目前 `k3s` 重建入口：

- `autoscale-source-split/01-monitoring-layer/k8s-expose/`
- `k3s-migration-bundle-sanitized/monitoring/live-exports/`
- `k3s-migration-bundle-sanitized/cluster-access/live-exports/`
- `k3s-migration-bundle-sanitized/separation-audit/`

## Candidate Files Not Recommended As Current Rebuild Entrypoints

以下檔案仍保留，但不建議在新的 `k3s` 重建時直接拿來當第一入口：

### Uncertain / keep for now

- `autoscale-source-split/03-shared-api-dashboard/autoscale_api/app/services/fan_cycle_experiment_service.py`
  - 屬 experiment API，未納入本次驗收，但未確定未來是否還要接回
- `autoscale-source-split/03-shared-api-dashboard/autoscale_api/app/services/yolo_demo_service.py`
  - 明顯綁舊 worker 與舊實驗環境；目前對 `Cluster Monitor` 非必要，但可能仍是之後 experiment 接回的基礎
- `autoscale-source-split/03-shared-api-dashboard/autoscale_api/scripts/plot_stress_trends.py`
  - 明顯偏舊 experiment/stress workflow；不屬目前監控主線，但未確認是否完全棄用
- `autoscale-source-split/03-shared-api-dashboard/autoscale_api/scripts/record_stress_metrics.py`
  - 與 stress/experiment workflow 相關；非目前監控主線必要
- `autoscale-source-split/03-shared-api-dashboard/autoscale_api/deploy/inventory-collector.yaml`
  - 未列入本次本地 API/dashboard 驗證流程；用途可能是後續 inventory 自動化
- `autoscale-source-split/03-shared-api-dashboard/autoscale_api/scripts/fetch_inventory_from_ds.py`
  - 同上，偏 inventory helper，不是監控重建主入口

### Not removed because needed for follow-up experiment work

- `autoscale-source-split/02-experiment-layer/**`
  - 雖未完成目前 `k3s` 驗收，但必要 source/workload 已保留，供下一台 `k3s` 環境接續實驗層開發
- `k3s-migration-bundle-sanitized/thermal-yolo/**`
  - 作為原交付 experiment/reference 對照，後續實驗層移植時仍有參考價值

## Practical Conclusion

若目標是移植到另一台 `k3s` 重建，目前應只聚焦：

- `MONITORING_REBUILD_SOP.md`
- `monitoring-rebuild/`
- `autoscale-source-split/01-monitoring-layer/` 必要腳本與 env 範本
- `autoscale-source-split/03-shared-api-dashboard/` 的 API / Cluster Monitor 主線

`02-experiment-layer` 與 `thermal-yolo` 現階段應視為後續工作，不應混入目前監控重建包的主入口。
