# Monitoring Rebuild Progress

Date: 2026-05-27
Workspace: `/home/icclz2/Pre6G`

## Summary

目前 `Pre6G` 的 `k3s` 監控主線已可作為重建基底：

- `monitoring-rebuild/` 已包含核心監控、GPU auto-discovery 與目前環境可用的 Netdata 重建入口
- `vm_aggregator` 可用
- `autoscale_api` 可啟動
- `cluster-dashboard` 的 `Cluster Monitor` 可顯示資料

目前交付狀態可視為：

- `iccl-cluster-z2`：基本監控正常
- `icclz3`：基本監控正常
- `z590-aorus-xtreme`：GPU node 曾驗證可用，但仍受磁碟壓力影響，不列為穩定重建驗收節點
- `mirc516-20250605`：已完成 GPU auto-discovery，但主機 NVIDIA driver/userspace mismatch，GPU metrics 尚未恢復
- API / dashboard：`Cluster Monitor` 已驗證；experiment 頁面不列入本次重建範圍

## Completed

### 1. Core monitoring stack

已整理為可重建基底：

- `VictoriaMetrics`
- `vmagent` cluster collector
- `vmagent-node-local` DaemonSet
- `node-exporter`
- `kube-state-metrics`
- `Netdata parent`
- `Netdata child`
- `Netdata k8s-state`

對應 manifests：

- [monitoring-rebuild/00-namespaces.yaml](/home/icclz2/Pre6G/monitoring-rebuild/00-namespaces.yaml)
- [monitoring-rebuild/10-victoria-metrics.yaml](/home/icclz2/Pre6G/monitoring-rebuild/10-victoria-metrics.yaml)
- [monitoring-rebuild/20-vmagent.yaml](/home/icclz2/Pre6G/monitoring-rebuild/20-vmagent.yaml)
- [monitoring-rebuild/30-node-exporter.yaml](/home/icclz2/Pre6G/monitoring-rebuild/30-node-exporter.yaml)
- [monitoring-rebuild/40-kube-state-metrics.yaml](/home/icclz2/Pre6G/monitoring-rebuild/40-kube-state-metrics.yaml)
- [monitoring-rebuild/45-nvidia-device-plugin.yaml](/home/icclz2/Pre6G/monitoring-rebuild/45-nvidia-device-plugin.yaml)
- [monitoring-rebuild/55-netdata.yaml](/home/icclz2/Pre6G/monitoring-rebuild/55-netdata.yaml)
- [monitoring-rebuild/60-netdata-child-stream-config.yaml](/home/icclz2/Pre6G/monitoring-rebuild/60-netdata-child-stream-config.yaml)

### 2. GPU monitoring and auto-discovery

已完成：

- `Node Feature Discovery`
- GPU alias rule
- `nvidia-device-plugin` 依 GPU label 自動排程
- `dcgm-exporter` 依 GPU label 自動排程

對應 manifests：

- [monitoring-rebuild/50-dcgm-exporter.yaml](/home/icclz2/Pre6G/monitoring-rebuild/50-dcgm-exporter.yaml)
- [monitoring-rebuild/70-node-feature-discovery.yaml](/home/icclz2/Pre6G/monitoring-rebuild/70-node-feature-discovery.yaml)
- [monitoring-rebuild/71-nfd-gpu-alias-rule.yaml](/home/icclz2/Pre6G/monitoring-rebuild/71-nfd-gpu-alias-rule.yaml)

目前不再需要手動 `accelerator=nvidia` 當作主要機制。

### 3. API / Dashboard

已整理並驗證：

- `autoscale_api` 可由本地腳本啟動
- `cluster-dashboard` 可由本地腳本啟動
- `Cluster Monitor` 頁面可正常顯示節點資料

相關入口：

- [autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh](/home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh)
- [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh](/home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh)

## Current Runtime Snapshot

截至 2026-05-27 確認：

- `kubectl get nodes -o wide` 可見 4 台節點：
  - `iccl-cluster-z2`
  - `icclz3`
  - `mirc516-20250605`
  - `z590-aorus-xtreme`
- 所有節點皆 `Ready`
- `Cluster Monitor` 可顯示 4 台節點的 inventory / status

## Validation Results

### Monitoring

已驗證：

- `kubectl get pods -A` 可觀察 monitoring stack
- `VictoriaMetrics` 可查到 `up`、`node_cpu_seconds_total`、`node_uname_info`
- GPU 正常節點時可查到 `DCGM_FI_DEV_GPU_TEMP`
- `run_vm_aggregator_once.sh iccl-cluster-z2` → `collector_status = ok`
- `run_vm_aggregator_once.sh icclz3` → `collector_status = ok`

### Dashboard / API

已驗證：

- `autoscale_api` 可回應 `GET /`、`GET /api/v1/nodes`、`GET /api/v1/nodes/status`
- `cluster-dashboard` 的 `Cluster Monitor` 可正常載入與顯示資料

## Known Issues

### 1. `mirc516-20250605` GPU host problem

此節點已完成 GPU auto-discovery，但 host NVIDIA stack 異常：

- kernel module: `570.211.01`
- userspace NVML / CUDA libs: `580.159.03`
- `nvidia-smi` 失敗
- `nvidia-device-plugin` / `dcgm-exporter` 報 `Driver/library version mismatch`

因此：

- GPU label 已自動出現
- 但 `nvidia.com/gpu` 尚未恢復

### 2. `z590-aorus-xtreme` stability

- 仍受主機磁碟壓力影響
- 不建議當作目前重建驗收的穩定 GPU 節點

### 3. VictoriaMetrics persistence

- `VictoriaMetrics` 目前仍使用非持久化配置
- 若正式環境需要長期保留 metrics，仍需補 storage 設計

## Practical Completion Estimate

若只看本次範圍 `monitor + dashboard(不含 experiment)`：

- `01-monitoring-layer`: 約 `90% ~ 95%`
- `03-shared-api-dashboard` 的 `Cluster Monitor` 主線：約 `85% ~ 90%`
- 整體作為 `k3s` 重建交付基底：約 `90%`

剩餘工作主要是：

- 修正文檔與入口一致性
- 決定是否為 `VictoriaMetrics` 補持久化
- 修復 `mirc516-20250605` 主機 NVIDIA stack
