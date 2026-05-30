# Monitoring Rebuild K3s Migration Notes

Date: 2026-05-23
Scope: `Pre6G` 交付包在新 `k3s` 環境上的監控層移植測試

## Purpose

本文件整理這次 `k3s` 移植測試中實際遇到的問題、處理方式，以及之後切到正式節點時建議直接沿用的快速重建做法。

## Executive Summary

這次重建證明：

- `Pre6G` 交付包中的監控設計可以移植到新 `k3s`
- 但不能直接原封不動套用所有 YAML
- 需要先處理 GPU node registration
- 需要改掉舊 cluster 的固定 IP 假設
- 對多網段環境，`vmagent` 不能只維持單點直抓所有 worker

目前測試結論：

- `z590-aorus-xtreme`：GPU 註冊與 DCGM 曾驗證成功，但目前受主機磁碟滿影響，不列為穩定監控節點
- `iccl-cluster-z2`：成功
- `icclz1`：新增後已自動套用完整監控，並被辨識為 `GTX 1080 Ti` GPU worker
- `icclz3`：已修復成功

因此之後切到正式節點時，建議把這次整理出的 `monitoring-rebuild/` 當成新基底，並直接沿用分散式 `vmagent` 設計，而不是回到單一 `vmagent` 直抓所有 node IP。

## Rebuild Flow That Worked

1. 先確認 `k3s` node 都 `Ready`
2. 先修 GPU node，使 `k3s` 真的看到 `nvidia.com/gpu`
3. 補 GPU label，讓 `dcgm-exporter` 能沿用原本 selector
4. 部署核心監控 stack
5. 將 `vmagent` 調整為：
   - cluster collector Deployment
   - node-local collector DaemonSet
6. 驗證 `VictoriaMetrics <- vmagent <- node-exporter / kube-state-metrics / dcgm-exporter`
7. 補 `Netdata`
8. 驗證 `vm_aggregator.py`

## Problems And Fixes

### 1. Device plugin 在所有 node 上跑，但 GPU 沒被註冊

症狀：

- `nvidia-device-plugin` pod 已在跑
- `z590-aorus-xtreme` 沒有 `nvidia.com/gpu`
- plugin log 顯示 `No devices found`

解法：

- 初期過渡修法曾為現有 `kube-system/nvidia-device-plugin-daemonset` 補上：
  - `runtimeClassName: nvidia`
  - 臨時 GPU node selector
- 之後已由 `Node Feature Discovery` + `feature.node.kubernetes.io/pci-10de.present=true` 取代手動 GPU 標記

結果：

- plugin 只跑在自動辨識出的 GPU node
- `nvidia.com/gpu` 可由 plugin 向 kubelet 註冊

### 2. 原交付包依賴 GPU label，但新 node 一開始沒有自動帶出

交付包原始邏輯：

- `dcgm-exporter` 依賴 `feature.node.kubernetes.io/pci-10de.present=true`

過渡期修法：

- 曾短暫以手動 label 驗證 selector 可用

正式收斂做法：

- 部署 `Node Feature Discovery`
- 用 [monitoring-rebuild/71-nfd-gpu-alias-rule.yaml](monitoring-rebuild/71-nfd-gpu-alias-rule.yaml) 將 upstream NFD label 映射為 bundle 既有的 `pci-10de.present=true`

結果：

- `dcgm-exporter` 與 `nvidia-device-plugin` 都可沿用原 bundle 風格 selector，且不再依賴手動 label

### 3. 舊 vmagent 設定含固定舊 IP，不能直接沿用

舊假設包含：

- 舊控制平面固定 IP 對 kubelet/cadvisor 的直連路徑
- 舊 `VictoriaMetrics NodePort` 假設
- 舊 lab API 路徑

解法：

- 不直接沿用舊 `helm-values-vmagent.current.yaml`
- 改用新整理的 [monitoring-rebuild/20-vmagent.yaml](monitoring-rebuild/20-vmagent.yaml)

### 4. 單一 vmagent 跨網段直抓 worker 會失敗

原始現象：

- 單一 `vmagent` 跑在 `z590-aorus-xtreme`
- `vmagent -> icclz3:9100` timeout
- `vm_aggregator.py` 對 `icclz3` 失敗

原因判斷：

- 不是 `k3s` 不能跨網段
- 是單一 collector 對異網段 worker 的主動 scrape 路徑不穩或不可達

成功解法：

- 保留中央 `vmagent` Deployment，只抓 cluster-wide 指標：
  - `kube-state-metrics`
  - `dcgm-exporter`
- 新增 `vmagent-node-local` DaemonSet
- 每顆 node-local `vmagent` 只抓本機：
  - `node-exporter`
  - `kubelet-cadvisor`
- 每顆 node-local `vmagent` 再將資料 remote write 回中央 `VictoriaMetrics`

### 5. `hostNetwork` 下 `icclz3` 對 cluster DNS 不穩

在 `vmagent-node-local` 採 `hostNetwork` 後，發現 `icclz3` 上的問題變成：

- 可抓本機 `127.0.0.1:9100`
- 但無法穩定解析：
  - `kubernetes.default.svc`
  - `vm-victoria-metrics-single-server.monitoring.svc`

log 會出現：

- `lookup ... on 10.43.0.10:53: i/o timeout`

成功解法：

- `kubelet-cadvisor` 改走控制平面 IP：
  - `https://140.113.179.9:6443/api/v1/nodes/<node>/proxy/metrics/cadvisor`
- `remoteWrite.url` 改走 `VictoriaMetrics NodePort`：
  - `http://140.113.179.9:31888/api/v1/write`

結果：

- `icclz3` 本機 scrape 正常
- `icclz3` metrics 成功寫回中央
- `vm_aggregator.py` 對 `icclz3` 恢復 `collector_status = ok`

### 6. `icclz3` 的 Netdata child 能跑，但 parent 沒有 host-scoped 視圖

原始現象：

- `vm_aggregator.py` 對 `icclz3` 雖可回 `collector_status = ok`
- 但 `_debug` 內大量 `netdata_*_error = HTTP Error 404: Not Found`
- `Netdata parent` 的 `/host/icclz3/...` 路徑沒有資料

原因判斷：

- `icclz3` 上的 `Netdata child` 以 `hostNetwork` 執行時，無法穩定解析 `netdata.netdata.svc`
- child 雖然 pod 是 `Running`，但其實沒有成功向 parent 建立 streaming session

成功解法：

- 檢查 `netdata-child` log，確認出現：
  - `Temporary failure in name resolution`
- 將 child stream destination 從 service DNS 改為控制平面 NodePort：
  - `140.113.179.9:32163`
- 將 working 設定保存為 [monitoring-rebuild/60-netdata-child-stream-config.yaml](monitoring-rebuild/60-netdata-child-stream-config.yaml)
- 重啟 `netdata-child` pods 讓新 stream 目的地生效
- 驗證 `Netdata parent` 的 `mirrored_hosts` 已包含 `icclz3`
- 驗證 `http://140.113.179.9:32163/host/icclz3/api/v1/charts` 回 `200`

結果：

- `icclz3` 的 host-scoped Netdata 視圖已建立
- `vm_aggregator.py` 對 `icclz3` 的 Netdata 404 已消失
- `node_pressure_instant` 與 `namespace_total_instant_local` 皆可正常帶出 Netdata 補充值

### 7. 中央監控不應放在磁碟異常的 GPU worker

原始現象：

- `z590-aorus-xtreme` 後續出現磁碟滿
- `VictoriaMetrics`、中央 `vmagent`、`kube-state-metrics` 若仍放在該節點，會出現 `Pending`、`Failed` 或被驅逐

成功解法：

- 將中央元件移到 `iccl-cluster-z2`：
  - `VictoriaMetrics`
  - `vmagent-victoria-metrics-agent`
  - `kube-state-metrics`
- 保留 GPU worker 只承擔 GPU exporter / device plugin / node-local collector

結果：

- 中央監控恢復穩定
- `run_vm_aggregator_once.sh` 也改為預設走 `140.113.179.9` 的 NodePort

## Additional Validated Outcome

後續新增 `icclz1` 加入目前 `k3s` 後，已驗證：

- `node-exporter`、`vmagent-node-local`、`Netdata child` 自動套用成功
- `Node Feature Discovery` 已自動補上 GPU 相關 label
- `nvidia-device-plugin`、`dcgm-exporter` 已自動排程到 `icclz1`
- `nvidia.com/gpu` 已出現在 node `Capacity` / `Allocatable`，值為 `1`
- `vm_aggregator` 已成功讀到 `NVIDIA GeForce GTX 1080 Ti` 指標

這代表目前的 `NFD + device-plugin + dcgm-exporter + node-local vmagent` 設計，對新加入的 NVIDIA GPU worker 已可自動接管。

## Recommended Formal Layout

對正式節點，建議直接沿用這次成功驗證的拓樸：

- 中央儲存：`VictoriaMetrics`
- 中央 cluster collector：單一 `vmagent` Deployment
- 節點本地 collector：`vmagent-node-local` DaemonSet
- 每個 node：
  - `node-exporter`
  - `Netdata child`
- 每個 GPU node：
  - `dcgm-exporter`
  - `nvidia-device-plugin`

## What Is Replaced By `monitoring-rebuild/`

這次新增的 `monitoring-rebuild/` 是新環境實際落地版。

以下交付包檔案已被它實質取代為新的安裝基底：

### Namespace / core monitoring

- 取代用途：
  - `k3s-migration-bundle-sanitized/monitoring/live-exports/helm-manifests/*`
  - `k3s-migration-bundle-sanitized/monitoring/live-exports/helm-values-*.current.yaml`
  - `k3s-migration-bundle-sanitized/monitoring/live-exports/vmagent-config.current.yaml`

對應新檔：

- [monitoring-rebuild/00-namespaces.yaml](monitoring-rebuild/00-namespaces.yaml)
- [monitoring-rebuild/10-victoria-metrics.yaml](monitoring-rebuild/10-victoria-metrics.yaml)
- [monitoring-rebuild/20-vmagent.yaml](monitoring-rebuild/20-vmagent.yaml)
- [monitoring-rebuild/30-node-exporter.yaml](monitoring-rebuild/30-node-exporter.yaml)
- [monitoring-rebuild/40-kube-state-metrics.yaml](monitoring-rebuild/40-kube-state-metrics.yaml)

### GPU monitoring

- 取代用途：
  - `k3s-migration-bundle-sanitized/gpu/dcgm-exporter.yaml`
  - `k3s-migration-bundle-sanitized/monitoring/live-exports/helm-manifests/helm-manifest-dcgm-exporter.yaml`

對應新檔：

- [monitoring-rebuild/50-dcgm-exporter.yaml](monitoring-rebuild/50-dcgm-exporter.yaml)
- [monitoring-rebuild/60-netdata-child-stream-config.yaml](monitoring-rebuild/60-netdata-child-stream-config.yaml)

### Exposure and query entrypoints

以下新檔已成為實際使用入口：

- [autoscale-source-split/01-monitoring-layer/run_vm_aggregator_once.sh](autoscale-source-split/01-monitoring-layer/run_vm_aggregator_once.sh)
- [autoscale-source-split/01-monitoring-layer/vm-aggregator-job.incluster.yaml](autoscale-source-split/01-monitoring-layer/vm-aggregator-job.incluster.yaml)

以下仍保留原檔直接沿用：

- [monitoring-rebuild/60-netdata-child-stream-config.yaml](monitoring-rebuild/60-netdata-child-stream-config.yaml)

以下已被新檔整合吸收：

- `autoscale-source-split/01-monitoring-layer/k8s-expose/*`（已移除）
- `k3s-migration-bundle-sanitized/cluster-access/victoria-metrics-nodeport.yaml`
- `k3s-migration-bundle-sanitized/cluster-access/vm-aggregator-job.incluster.yaml`

因為現在實際對外與 in-cluster 查詢都已改以 `iccl-cluster-z2` 的 NodePort 為準。

## What Is Still Reference-Only

以下檔案仍有參考價值，但不建議直接當成新環境的第一安裝來源：

- `monitoring-rebuild/helm-values-*.current.yaml`
- `monitoring-rebuild/helm-manifests/*`
- `monitoring-rebuild/vmagent-config.current.yaml`
- `k3s-migration-bundle-sanitized/monitoring/vmagent-config-with-rfsoc4x2.yaml`
- `k3s-migration-bundle-sanitized/nvidia-device-plugin/*`
- `k3s-migration-bundle-sanitized/cluster-access/vm-aggregator-job.incluster.yaml`

另外，正式重建時建議直接先套用：

- [monitoring-rebuild/60-netdata-child-stream-config.yaml](monitoring-rebuild/60-netdata-child-stream-config.yaml)

以確保 `netdata-conf-child` 直接走已驗證可用的 NodePort 目的地。

以下 Netdata 來源檔仍有參考價值，但正式多網段環境若仍使用 `hostNetwork`，需留意 service DNS 可能不穩：

- `autoscale-source-split/01-monitoring-layer/netdata-default-values.yaml`
- `monitoring-rebuild/helm-manifests/helm-manifest-netdata.yaml`

## Minimal Acceptance Criteria For Next Rebuild

正式重建時，至少要達成：

- `kubectl get pods -A` 中 monitoring 相關 pod 全部 `Running`
- `DCGM_FI_DEV_GPU_TEMP` 可查到
- `node_cpu_seconds_total` 可查到
- `node_uname_info` 可查到所有預期節點
- `vm_aggregator.py` 對所有目標節點皆 `collector_status = ok`
- `vm_aggregator.py` 不再出現 `netdata_*_error = HTTP Error 404`

## Current Practical Conclusion

如果要對外簡短描述本次移植測試結果，可用：

「本次 `k3s` 監控層移植測試已完成核心鏈路驗證，並成功將 `vmagent` 由單點直抓調整為分散式收集。`iccl-cluster-z2` 與 `icclz3` 的監控與 `vm_aggregator.py` 已驗證可用；`z590-aorus-xtreme` 的 GPU 監控鏈路曾驗證成功，但目前因主機磁碟滿暫列異常，待正式節點重建時再恢復為穩定 GPU 節點。」


## GPU Auto-Discovery Notes

The rebuilt cluster no longer needs a manual `accelerator=nvidia` label for new GPU workers.

Implemented approach:
- `Node Feature Discovery` is deployed to discover PCI devices on each node.
- Upstream NFD emits labels like `feature.node.kubernetes.io/pci-0300_10de.present=true` for NVIDIA display-class PCI devices.
- To stay compatible with the delivery bundle, [monitoring-rebuild/71-nfd-gpu-alias-rule.yaml](monitoring-rebuild/71-nfd-gpu-alias-rule.yaml) maps that upstream label back to `feature.node.kubernetes.io/pci-10de.present=true`.
- `nvidia-device-plugin` and `dcgm-exporter` selectors should continue using `feature.node.kubernetes.io/pci-10de.present=true`.

Observed on new node `mirc516-20250605`:
- Automatic PCI discovery worked.
- Bundle-style label `feature.node.kubernetes.io/pci-10de.present=true` appeared automatically.
- `nvidia-device-plugin` and `dcgm-exporter` automatically scheduled to the node.
- Final failure was host-side: `failed to initialize NVML: Driver/library version mismatch`.

Confirmed example on `mirc516-20250605`:
- `/proc/driver/nvidia/version` reported kernel module `570.211.01`.
- `libnvidia-ml.so.1` and `libcuda.so.1` resolved to `580.159.03`.
- `dpkg -l` showed a mixed install of `570-server` and `580-server` NVIDIA packages.
- Host `nvidia-smi` already failed before Kubernetes could register `nvidia.com/gpu`.

Practical interpretation: if NFD labels and selector-based scheduling look correct but `nvidia-device-plugin` still fails with NVML mismatch, fix the host driver/userspace stack first; Kubernetes manifests are no longer the blocker.

Implication for future rebuilds:
- If a new GPU node has the auto label but still does not get `nvidia.com/gpu`, inspect the host NVIDIA driver / userspace stack before changing Kubernetes selectors.
