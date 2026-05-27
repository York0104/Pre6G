# 01 Monitoring Layer

本層保存 AutoScale 監控與 metrics 聚合相關 source/config。它應可在任何 YOLO 或 thermal 實驗啟動前獨立恢復。

## 主要用途

- 從 VictoriaMetrics、Netdata、DCGM exporter、AP gateway、RFSoC、Kubernetes/cAdvisor 讀取 metrics。
- 彙整成 AutoScale API 與實驗分析可使用的節點狀態。
- 保存監控相關的 service exposure 參考、systemd service template 與交接文件。

## 檔案與目錄說明

| 路徑 | 說明 |
| --- | --- |
| `vm_aggregator.py` | 目前主要 K8s/GPU node aggregator；已使用統一命名。 |
| `vm_agg_rfsoc.py` | RFSoC 外部節點 aggregator，彙整 RFSoC/Netdata/VictoriaMetrics 狀態。 |
| `vm_agg_ap_gateway.py` | OpenWrt AP / AP gateway aggregator。 |
| `netdata_client.py` | Netdata API 查詢 helper。 |
| `collector_nodes.json` | aggregator 節點清單與 target 設定參考。 |
| `collect_full_metrics_api_csv.py` | 從 AutoScale full metrics API 週期性收集 CSV。 |
| `collect_node_metrics_csv.py` | 針對單一 node 收集 metrics CSV。 |
| `run_full_metrics_api_collector.sh` | 啟動 full metrics API collector 的 shell wrapper。 |
| `run_vm_aggregator_once.sh` | 單次執行 aggregator 的 smoke test wrapper。 |
| `monitoring-runtime.host.env.example` | host 端監控/API 共用端點參數範本。 |
| `monitoring-runtime.incluster.env.example` | cluster 內 Job/Pod 用的端點參數範本。 |
| `ap_gateway/` | AP gateway 設計文件與 SNMP gateway 程式。 |
| `netdata-default-values.yaml` | Netdata Helm values/reference。 |
| `vm-aggregator-job.incluster.yaml` | 在 cluster 內執行 aggregator 的 Job 參考。 |
| `systemd/autoscale-api.service` | AutoScale API systemd service template。 |
| `systemd/autoscale-api.env.example` | AutoScale API 環境變數範例；真實 env 不在此層。 |
| `docs/frontend-api-handoff.md` | 前端與 API 對接欄位說明。 |
| `docs/full-metrics-handoff.md` | full metrics API/collector 交接說明。 |
| `docs/api-dashboard-bootstrap.md` | AutoScale API 與 dashboard 接線/驗證說明。 |
| `docs/vm-aggregators-reference.md` | 各 aggregator schema、欄位與資料來源比較。 |

## Exposure

目前實際使用的 exposure 基底已移到 `monitoring-rebuild/`：

- `monitoring-rebuild/10-victoria-metrics.yaml`
- `monitoring-rebuild/45-nvidia-device-plugin.yaml`
- `monitoring-rebuild/55-netdata.yaml`
- `monitoring-rebuild/60-netdata-child-stream-config.yaml`

舊 `k8s-expose/` 目錄已移除，避免與目前 `k3s` 重建基底重複或造成誤導。

## `ap_gateway/`

| 檔案 | 說明 |
| --- | --- |
| `AP_GATEWAY_DESIGN.md` | AP gateway 設計與資料流說明。 |
| `ap_gateway.py` | AP gateway collector 主程式。 |
| `ap_snmp_gateway.py` | OpenWrt AP SNMP gateway 程式。 |

## `systemd/`

| 檔案 | 說明 |
| --- | --- |
| `autoscale-api.service` | AutoScale API systemd service template。 |
| `autoscale-api.env.example` | AutoScale API env 範例，不含真實 secret。 |

## 注意事項

- 本層只提供 source/config；實際 kubeconfig、SSH key、API env 在 private handoff。
- 若實驗層需要 aggregator，應指向本層 `vm_aggregator.py`。
- `MONITORING_REBUILD_SOP.md` 是目前正式重建入口；本 README 只做目錄索引。
