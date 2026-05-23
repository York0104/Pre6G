# GPU / DCGM

本資料夾保存 dcgm-exporter Helm values 與自訂 DCGM metrics ConfigMap。

| 檔案 | 說明 |
| --- | --- |
| `helm-values-dcgm-exporter.current.yaml` | 來源 cluster 匯出的 DCGM exporter Helm values。 |
| `exporter-metrics-config-map.current.yaml` | 來源 cluster 目前使用的 DCGM metrics ConfigMap。 |
| `exporter-metrics-config-map.new.yaml` | 本機整理的 metrics whitelist copy。 |
| `exporter-metrics-config-map.backup.yaml` | 舊版/備份 ConfigMap，僅供比對。 |
| `dcgm-exporter.yaml` | DCGM exporter manifest 參考。 |
| `dcgm-exporter.backup.yaml` | 舊版/備份 manifest，僅供比對。 |
| `dcgm-values.yaml` | setup 時使用的 compact values。 |

thermal experiments 依賴 GPU temperature、SM clock、power usage、GPU utilization、thermal/power violation counters。請確認自訂 ConfigMap 有掛載為 dcgm-exporter 的 `default-counters.csv`。
