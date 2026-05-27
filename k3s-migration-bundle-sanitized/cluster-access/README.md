# Cluster Access / Exposure

本資料夾保存 cluster-level helper manifests 與 `k3s` 重建時仍可能用到的 exposure 參考。

| 檔案/目錄 | 說明 |
| --- | --- |
| `calico-installation-tailscale0.yaml` | Calico/Tailscale interface 參考。 |
| `custom-resources.yaml` | Calico operator `Installation` / `APIServer` CR 參考。 |
| `victoria-metrics-nodeport.yaml` | VictoriaMetrics NodePort exposure 舊參考；目前以 `monitoring-rebuild/10-victoria-metrics.yaml` 為準。 |
| `vm-aggregator-job.incluster.yaml` | 在 cluster 內執行 VM aggregator 的 Job 參考。 |

Calico 相關 manifests 只有在新 cluster 網路假設一致時才建議沿用。

## Legacy Note

舊 `live-exports/` 快照已移除，避免與目前 `k3s` 重建資訊重複或造成誤導。
若需要目前可用的 VM query / exposure 入口，請以：

- `monitoring-rebuild/10-victoria-metrics.yaml`
- `autoscale-source-split/01-monitoring-layer/vm-aggregator-job.incluster.yaml`

為準。
