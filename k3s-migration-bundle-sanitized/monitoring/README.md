# Monitoring

本資料夾保存 VictoriaMetrics、vmagent、node-exporter、kube-state-metrics 與 scrape config 參考。

## 主要檔案

| 路徑 | 說明 |
| --- | --- |
| `scrape.yml` | vmagent scrape source 參考。 |
| `vmagent-config-auto-discovery.yaml` | 自動 discovery 版 scrape config 參考。 |
| `vmagent-config-gpu-1s.yaml` | GPU 1 秒 scrape interval 參考。 |
| `vmagent-config-with-rfsoc4x2.yaml` | 含 RFSoC scrape target 的 vmagent config。 |
| `vmagent-config-before-rfsoc4x2-lab.yaml` | RFSoC 加入前/過渡版本參考。 |
| `monitoring-rebuild/` | 新 `k3s` 環境實際落地版；應優先使用。 |

## Legacy Note

舊 `live-exports/` 快照已自本交付包移除，避免與目前 `k3s` 重建基底混淆。
若需要來源 cluster 的背景脈絡，請改看：

- `MONITORING_REBUILD_SOP.md`
- `MONITORING_REBUILD_K3S_MIGRATION_NOTES.md`
- `monitoring-rebuild/`

## 重建後驗證

- vmagent `/targets` 應包含 `node-exporter`、`kubelet-cadvisor`、`dcgm-exporter`、`rfsoc4x2-node-exporter`。
- VictoriaMetrics 應接受 remote write：`http://vm-victoria-metrics-single-server.monitoring.svc:8428/api/v1/write`。
- PromQL 應可查詢 `node_cpu_seconds_total`、`container_cpu_usage_seconds_total`、`DCGM_FI_DEV_GPU_TEMP`。
