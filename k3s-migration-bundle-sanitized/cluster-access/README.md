# Cluster Access / Exposure

本資料夾保存 cluster-level helper manifests 與來源 cluster 版本參考。

| 檔案/目錄 | 說明 |
| --- | --- |
| `calico-installation-tailscale0.yaml` | Calico/Tailscale interface 參考。 |
| `custom-resources.yaml` | Calico operator `Installation` / `APIServer` CR 參考。 |
| `victoria-metrics-nodeport.yaml` | VictoriaMetrics NodePort exposure manifest。 |
| `vm-aggregator-job.incluster.yaml` | 在 cluster 內執行 VM aggregator 的 Job 參考。 |
| `live-exports/` | 來源 cluster node、node version、kubectl client version 參考。 |

Calico 相關 manifests 只有在新 cluster 網路假設一致時才建議沿用。
