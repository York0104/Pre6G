# Project Status

Date: 2026-06-24  
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
- **剩餘未完成項主要集中在 RFSoC 長期穩定性與進階 PL telemetry，以及少數非主線補件**

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
- `Fan-Cycle Experiment` host-side rebuild
- `Gemma 4 vLLM` workload monitoring 第一版 source 實作

目前 API / dashboard 已可服務一般 `k3s` nodes 與 external nodes inventory/status；`Fan-Cycle Experiment` 也已重建為目前實驗室環境可操作的 host-side console。

另外已新增 workload-centric 第一版能力：

- `vLLM` 原生 Prometheus metrics 接入既有 `vmagent -> VictoriaMetrics`
- `autoscale_api` workload API 與 vLLM adapter
- dashboard `LLM Workloads` 區塊

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

真實 telemetry 已完成基本恢復與驗證；目前工作重點轉為長期穩定性與進階 PL telemetry。

### 2. Private/public config structure

目前已整理：

- `Pre6G/config/`：公開設定與常用 manifests 入口
- `~/pre6g-private/`：私有 live 設定入口

但系統 live 路徑尚未全面重構成正式 symlink 管理架構；目前是先完成入口整理，不主動搬動正在運作的 live 路徑。

### 3. Fan-Cycle Experiment productization

目前已完成：

- dashboard UI wiring
- API `status/start/stop`
- runtime env contract
- 與 `02-experiment-layer` single-pod fan-cycle workflow 對齊

但尚未完成：

- 一般化 `k3s` Pod 內 end-to-end 驗證
- 不依賴 host-side SSH / worker private runtime 的完整產品化封裝

### 4. LLM workload monitoring rollout

目前已完成：

- `Gemma 4 vLLM` manifest
- vmagent workload scrape job
- workload API / dashboard source 實作
- live Pod `/metrics` 與 VictoriaMetrics metric existence 驗證

目前尚待補齊：

- cluster 內正式重建 `autoscale_api` / dashboard image
- benchmark job 正式結果
- 新 workload API 的 live HTTP smoke test 再跑一次

## Not Yet Completed

### 1. External node real telemetry recovery

目前主要未完成項：

- `rfsoc4x2-pynq`
  - node-exporter、Netdata mirrored host、PYNQ/XRT SSH status 已恢復並可由 aggregator 取得
  - Dashboard 已顯示 RFSoC Hardware Status card，並以 `Accelerator: RFSoC PL + RFDC` 取代 GPU N/A
  - DMA producer 每 30 秒輸出 MM2S/S2MM health；目前兩 channel 均為 `ready`、非 halted 且無 error
  - PL LUT/FF/BRAM/DSP、DMA throughput、per-IP activity 與 RFDC PLL/tile state 尚待額外 producer 或 Vivado report
- `openwrt_ap`
  - 已經由 Tailscale target `100.101.18.10` 恢復真實 telemetry
  - SSH Wi-Fi collector 與 SNMP collector 均以 user-level systemd 常駐
  - dashboard 已顯示 AP 專屬無線資訊、資源、root disk 與 I/O 指標

### 2. Long-duration formal reruns

目前已完成正式 workflow 的縮短版驗證，但若要做最終論文級或長期實驗級驗收，仍可再補：

- full-duration thermal runs
- multi-repeat 長時間實驗
- 更完整的正式資料批次保存

## Recommended Next Steps

依優先順序建議：

1. 持續確認 `rfsoc4x2-pynq` 真實 telemetry 穩定性
2. 視需要補做 full-duration experiment reruns
3. 持續維護 `Pre6G/config/` 與 `pre6g-private/` 的 source-of-truth 分工

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
- [docs/rebuild/kaniko-yolo26-build-rebuild.md](docs/rebuild/kaniko-yolo26-build-rebuild.md)
