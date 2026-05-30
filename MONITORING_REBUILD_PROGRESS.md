# Monitoring Rebuild Progress

Date: 2026-05-28
Workspace: `/home/icclz2/Pre6G`

## Summary

目前 `Pre6G` 的 `k3s` 監控主線已可作為重建基底：

- `monitoring-rebuild/` 已包含核心監控、GPU auto-discovery 與目前環境可用的 Netdata 重建入口
- `vm_aggregator` 可用
- `autoscale_api` 可啟動
- `cluster-dashboard` 的 `Cluster Monitor` 可顯示資料

目前交付狀態可視為：

- `iccl-cluster-z2`：基本監控正常
- `icclz1`：新加入成功，已自動辨識為 `GTX 1080 Ti` GPU worker，監控正常
- `icclz3`：基本監控正常
- `z590-aorus-xtreme`：GPU node 曾驗證可用，但仍受磁碟壓力影響，不列為穩定重建驗收節點
- `mirc516-20250605`：已完成 GPU auto-discovery，但主機 NVIDIA driver/userspace mismatch，GPU metrics 尚未恢復
- API / dashboard：`Cluster Monitor` 已驗證；experiment 頁面不列入本次重建範圍
- `02-experiment-layer`：已在目前 k3s 環境恢復 `icclz1` shared-GPU YOLO 三實例主線，並完成短版 latency smoke test
- `RFSoC external monitoring`：已改以 Tailscale `100.91.37.32:9100` 接入目前 `VictoriaMetrics`，`Netdata parent` 已看到 `pynq`，`vm_agg_rfsoc.py` 已可輸出 `collector_status = ok`
- `K3s host-side vm_aggregator`：預設入口已同步到目前環境，改為 `VM_URL=http://140.113.179.9:31888`、`NETDATA_URL=http://140.113.179.9:32163`、`KSM_URL=http://140.113.179.9:32080`，避免裸跑時誤打舊的 cluster DNS service。
- `systemd` host-side runtime：`ap-gateway.service`、`ap-snmp-gateway.service`、`autoscale-api.service` 已完成安裝與啟動驗證，正式重建路徑已從 `tmux` 改為 `systemd`。
- `autoscale_api` token rotation：已完成實際 token 輪替，並補上文檔提醒 `autoscale-api.env` 不能只保留 `<control-plane-ip>` 範例值；否則 `full-metrics` 會出現 `RFSoC/AP 正常、所有 k8s nodes 同時失敗` 的假象。

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

- `autoscale_api` 已整理成 `systemd` 正式重建路徑，並保留本地腳本作為手動 fallback
- `cluster-dashboard` 可由本地腳本啟動
- `Cluster Monitor` 頁面可正常顯示節點資料

相關入口：

- [autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh](/home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh)
- [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh](/home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh)

## Current Runtime Snapshot

截至 2026-05-28 確認：

- `kubectl get nodes -o wide` 可見 5 台節點：
  - `iccl-cluster-z2`
  - `icclz1`
  - `icclz3`
  - `mirc516-20250605`
  - `z590-aorus-xtreme`
- 所有節點皆 `Ready`
- `Cluster Monitor` 可顯示 5 台節點的 inventory / status
- `icclz1` 已自動套用：
  - `node-exporter`
  - `vmagent-node-local`
  - `netdata-child`
  - `nfd-worker`
  - `nvidia-device-plugin`
  - `dcgm-exporter`

## Validation Results

### Monitoring

已驗證：

- `kubectl get pods -A` 可觀察 monitoring stack
- `VictoriaMetrics` 可查到 `up`、`node_cpu_seconds_total`、`node_uname_info`
- GPU 正常節點時可查到 `DCGM_FI_DEV_GPU_TEMP`
- `kubectl get node icclz1 -o jsonpath='{.status.capacity.nvidia\.com/gpu}'` → `1`
- `kubectl get node icclz1 -o jsonpath='{.status.allocatable.nvidia\.com/gpu}'` → `1`
- `run_vm_aggregator_once.sh iccl-cluster-z2` → `collector_status = ok`
- `run_vm_aggregator_once.sh icclz1` → `collector_status = ok`
- `run_vm_aggregator_once.sh icclz3` → `collector_status = ok`
- `VictoriaMetrics` 已可查到：
  - `up{job="node-exporter",instance="140.113.179.6:9100"} = 1`
  - `up{job="kubelet-cadvisor",kubernetes_node="icclz1"} = 1`
  - `DCGM_FI_DEV_GPU_TEMP{kubernetes_node="icclz1"}`
- `vm_aggregator` 已成功讀到 `icclz1` GPU：
  - `NVIDIA GeForce GTX 1080 Ti`
  - driver `535.309.01`
  - `capacity_gpus = 1` / `allocatable_gpus = 1`

### Dashboard / API

已驗證：

- `autoscale_api` 可回應 `GET /`、`GET /api/v1/nodes`、`GET /api/v1/nodes/status`
- `cluster-dashboard` 的 `Cluster Monitor` 可正常載入與顯示資料

### RFSoC External Monitoring

已驗證：

- `rfsoc4x2-node-exporter` 已透過 Tailscale target `100.91.37.32:9100` 接入目前 `vmagent` / `VictoriaMetrics`
- `up{job="rfsoc4x2-node-exporter",access="tailscale",board="RFSoC4x2"}` 查詢結果為 `1`
- 目前 `Netdata parent` `http://140.113.179.9:32163` 的 `mirrored_hosts` 已包含 `pynq`
- `http://140.113.179.9:32163/host/pynq/api/v1/data?...` 已可回 JSON
- `vm_agg_rfsoc.py` 已在目前主機以以下環境完成 live 驗證：
  - `NETDATA_URL=http://140.113.179.9:32163`
  - `VM_URL=http://140.113.179.9:31888`
  - `ACCESS=tailscale`
  - `INSTANCE=100.91.37.32:9100`
  - `PL_STATUS_SSH_TARGET=xilinx@100.91.37.32`
- `vm_agg_rfsoc.py` 已成功輸出：
  - `collector_status = ok`
  - `health.up = true`
  - `pl_status.*`
  - `node_pressure_instant.*`
  - `node_compute_features.*`

### 02 Experiment Layer

已驗證：

- `icclz1` 已啟用 `nvidia.com/gpu.shared: 4`
- `autoscale-source-split/02-experiment-layer/yolo26_k8s/build_and_import_image_to_k3s.sh` 可建立並匯入 `local/yolo26n:0.1` / `0.5`
- `intent-lab` 中 `yolo26n-focus`、`yolo26n-bg-1`、`yolo26n-bg-2` 可在 `icclz1` 上 `Running`
- `http://140.113.179.6:18081/healthz`、`18082`、`18083` 皆回 `200`
- 2026-05-28 短版 baseline smoke test：
  - focus `50/50` success，client mean `137.589 ms`，server mean `18.783 ms`
  - bg-1 `25/25` success，client mean `181.229 ms`，server mean `22.813 ms`
  - bg-2 `25/25` success，client mean `221.967 ms`，server mean `22.610 ms`
- smoke test 輸出已確認後刪除，只保留驗證結論

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

若看目前已完成主線：

- `01-monitoring-layer`: 約 `90% ~ 95%`
- `03-shared-api-dashboard` 的 `Cluster Monitor` 主線：約 `85% ~ 90%`
- `02-experiment-layer` 的 `icclz1` shared-GPU YOLO 主線：已可重現 baseline / 3-instance 入口，後續 thermal cycle 與完整批次實驗可在此基礎上繼續
- 整體作為 `k3s` 重建交付基底：約 `92%`

剩餘工作主要是：

- 決定是否為 `VictoriaMetrics` 補持久化
- 修復 `mirc516-20250605` 主機 NVIDIA stack
- 視需要再把 `02-experiment-layer` 的 thermal cycle / batch workflow 做完整驗收

## AP Gateway Rebuild Status

- `iccl-cluster-z2` host 端已可直接連到 OpenWrt AP `192.168.1.1:22` / `:80`：
  - `curl -I http://192.168.1.1` 回 `HTTP/1.1 200 OK`
  - `ssh -i ~/.ssh/openwrt_ap_ed25519 root@192.168.1.1 ...` 已可登入
- `ap_gateway.py`（Wi-Fi collector）與 `ap_snmp_gateway.py`（SNMP collector）都已打通，且正式重建路徑已整理為 host-side `systemd service`：
  - `ap-gateway.service`
  - `ap-snmp-gateway.service`
  - env 範本：`autoscale-source-split/01-monitoring-layer/systemd/ap-gateway.env.example`、`ap-snmp-gateway.env.example`
  - 既有 `runtime_logs/ap_gateway.log`、`ap_snmp_gateway.log` 可保留作為手動執行紀錄參考
- `autoscale_api`、`ap-gateway.service`、`ap-snmp-gateway.service` 的 `systemd` 安裝、啟動與驗證指令，已整理進：
  - `autoscale-source-split/03-shared-api-dashboard/autoscale_api/README.md`
  - `autoscale-source-split/03-shared-api-dashboard/LOCAL_BOOTSTRAP_STATUS.md`
  - `autoscale-source-split/01-monitoring-layer/ap_gateway/AP_GATEWAY_DESIGN.md`
- `VictoriaMetrics` 已可查到代表性 AP metrics：
  - `ap_wifi_station_count{ap="openwrt_ap"}`
  - `ap_node_cpu_usage_percent{ap="openwrt_ap"}`
- `vm_agg_ap_gateway.py` 已在目前環境完整輸出 `collector_status = ok`：
  - `wireless_access`、`stations` 已有值
  - `device_resource`、`interface_traffic`、`node_pressure`、`node_compute_features` 已由 SNMP metrics 補齊
- 另外已驗到 cluster 內 Pod 對 `192.168.1.1` 的可達性與 host 端不同：
  - `UDP/161` 可達
  - `TCP/22`、`TCP/80` timeout
  - 因此 AP collectors 目前仍建議先跑在 host 上，不建議先搬進 cluster Pod
- 後續維護重點：
  - 以 `systemctl status ap-gateway.service`、`systemctl status ap-snmp-gateway.service`、`journalctl -u ...` 作為主要維運入口
  - 若 OpenWrt SNMP community / iface index 變動，需同步更新 `ap-snmp-gateway.env` 或 collector 執行參數
  - `tmux` 只保留作為臨時除錯方式，不再作為正式重建路徑

