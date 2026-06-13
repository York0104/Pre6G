# Project Status

Date: 2026-06-13  
Workspace: `/home/icclz2/Pre6G`  
Primary host: `icclz2`  
Control plane IP: `140.113.179.9`

## Purpose

這份文件是目前 `Pre6G` repo 的**總計畫進度追蹤入口**。

用途是：

- 用高層摘要快速看目前整體重建做到哪
- 區分哪些主線已完成、哪些仍待補齊
- 提供下一步建議
- 導到更細部的技術文件

若要看具體操作、驗證細節、重建命令與各子系統說明，請往下方「Detailed References」查看。

## Overall Status

目前可將這次重建視為：

- **主線已完成，可用**
- **整體完成度約 `90% ~ 95%`**
- **剩餘未完成項主要集中在 external node 真實資料源恢復，以及少數非主線補件**

## Completed

### 1. K3s base and control plane

已完成：

- `k3s` control-plane 建立
- Kubernetes API 正常提供服務
- GPU worker `icclz1` 已重新接入目前環境

### 2. Monitoring layer

已完成並可用：

- `VictoriaMetrics`
- `vmagent`
- `vmagent-node-local`
- `node-exporter`
- `kube-state-metrics`
- `Netdata`
- `Node Feature Discovery`
- `nvidia-device-plugin`
- `dcgm-exporter`

目前 `monitoring-rebuild/` 已是正式主線 manifests。

### 3. Shared API and dashboard

已完成並可用：

- `autoscale_api`
- `Cluster Monitor` dashboard
- host-side Python venv / Node runtime
- user-level systemd 常駐啟動

目前 API / dashboard 已可服務一般 `k3s` nodes 與 external nodes inventory/status。

### 4. Experiment layer

已完成主線重建與驗證：

- `intent-lab` namespace
- `nvidia.com/gpu.shared: 4`
- YOLO26 三實例 hostPort stack
- baseline / `single_pod_serial` / `task3`
- `fault_fan` / `bgload_fan_cycle` 短版 smoke test
- formal thermal / rate-sweep workflow 縮短版驗證

### 5. Harbor registry workflow

已完成到實務可用：

- Harbor 已切換為 `HTTPS:8088`
- Harbor project / robot accounts 已建立
- `harbor.iccl.local:8088/pre6g/yolo26n:0.1` 已完成 build / tag / push
- `icclz1` 已成功使用 Harbor image
- registry 版三實例 `yolo26n-focus/bg-1/bg-2` 已回到 `Running`

### 6. Shareable bundle / external handoff

已完成：

- `shareable-bundles/full-metrics-api-collector`
- OpenWrt 環境前測與 collector 實跑驗證
- 對外交付 README 與 collector bundle 打包

## Partially Completed

### 1. External node integration

目前 external nodes 已完成：

- inventory 接入
- API / dashboard status 路徑接通
- RFSoC aggregator 邏輯補強

但真實 telemetry 恢復尚未全部完成。

### 2. Private/public config structure

目前已整理：

- `Pre6G/config/`：公開設定與常用 manifests 入口
- `~/pre6g-private/`：私有 live 設定入口

但系統 live 路徑尚未全面重構成正式 symlink 管理架構；目前是先完成入口整理，不主動搬動正在運作的 live 路徑。

## Not Yet Completed

### 1. External node real telemetry recovery

目前主要未完成項：

- `rfsoc4x2-pynq`
  - inventory / API 路徑已恢復
  - 真實資料源仍需持續確認與維護
- `openwrt_ap`
  - inventory / API 路徑已恢復
  - AP collectors / credentials / 真實 telemetry 仍未完整收斂

### 2. Long-duration formal reruns

目前已完成正式 workflow 的縮短版驗證，但若要做最終論文級或長期實驗級驗收，仍可再補：

- full-duration thermal runs
- multi-repeat 長時間實驗
- 更完整的正式資料批次保存

## Recommended Next Steps

依優先順序建議：

1. 恢復 `openwrt_ap` 真實 telemetry
2. 持續確認 `rfsoc4x2-pynq` 真實 telemetry 穩定性
3. 視需要補做 full-duration experiment reruns
4. 持續維護 `Pre6G/config/` 與 `pre6g-private/` 的 source-of-truth 分工

## Source of Truth

目前建議的文件分工如下：

- **總進度入口**
  - [PROJECT_STATUS.md](PROJECT_STATUS.md)
- **詳細重建進度**
  - [MONITORING_REBUILD_PROGRESS.md](MONITORING_REBUILD_PROGRESS.md)
- **正式重建 SOP**
  - [MONITORING_REBUILD_SOP.md](MONITORING_REBUILD_SOP.md)
- **公開設定與 manifests 入口**
  - [config/README.md](config/README.md)
- **私有 live 設定入口**
  - `~/pre6g-private/PRIVATE_ASSETS_README.md`

## Detailed References

### Root-level status and SOP

- [MONITORING_REBUILD_PROGRESS.md](MONITORING_REBUILD_PROGRESS.md)
- [MONITORING_REBUILD_SOP.md](MONITORING_REBUILD_SOP.md)
- [MONITORING_REBUILD_K3S_MIGRATION_NOTES.md](MONITORING_REBUILD_K3S_MIGRATION_NOTES.md)
- [K3S_REBUILD_PACKAGE_AUDIT.md](K3S_REBUILD_PACKAGE_AUDIT.md)

### Monitoring and config

- [config/README.md](config/README.md)
- [monitoring-rebuild/REBUILD_PARAMETERS.md](monitoring-rebuild/REBUILD_PARAMETERS.md)

### Experiment layer

- [autoscale-source-split/02-experiment-layer/README.md](autoscale-source-split/02-experiment-layer/README.md)
- [autoscale-source-split/02-experiment-layer/scripts/README_yolo26_3inst.md](autoscale-source-split/02-experiment-layer/scripts/README_yolo26_3inst.md)

### API / dashboard

- [autoscale-source-split/03-shared-api-dashboard/LOCAL_BOOTSTRAP_STATUS.md](autoscale-source-split/03-shared-api-dashboard/LOCAL_BOOTSTRAP_STATUS.md)
- [autoscale-source-split/03-shared-api-dashboard/autoscale_api/README.md](autoscale-source-split/03-shared-api-dashboard/autoscale_api/README.md)
- [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/README.md](autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/README.md)

### Harbor / registry

- [k3s-migration-bundle-sanitized/registry/REBUILD_STEPS.md](k3s-migration-bundle-sanitized/registry/REBUILD_STEPS.md)
- [k3s-migration-bundle-sanitized/registry/IMPLEMENTATION_PROGRESS.md](k3s-migration-bundle-sanitized/registry/IMPLEMENTATION_PROGRESS.md)
- [k3s-migration-bundle-sanitized/registry/VERIFY_REGISTRY_PULL.md](k3s-migration-bundle-sanitized/registry/VERIFY_REGISTRY_PULL.md)
