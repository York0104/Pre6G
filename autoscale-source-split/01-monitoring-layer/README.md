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
| `systemd/ap-gateway.service` | AP Wi-Fi collector systemd service template。 |
| `systemd/ap-gateway.env.example` | AP Wi-Fi collector env 範例。 |
| `systemd/ap-snmp-gateway.service` | AP SNMP collector systemd service template。 |
| `systemd/ap-snmp-gateway.env.example` | AP SNMP collector env 範例。 |
| `docs/frontend-api-handoff.md` | 前端與 API 對接欄位說明。 |
| `docs/full-metrics-handoff.md` | full metrics API/collector 交接說明。 |
| `docs/api-dashboard-bootstrap.md` | AutoScale API 與 dashboard 接線/驗證說明。 |
| `docs/vm-aggregators-reference.md` | 各 aggregator schema、欄位與資料來源比較。 |
| `docs/LLM_WORKLOAD_MONITORING_IMPLEMENTATION_LOG.md` | Gemma 4 vLLM workload 監控第一版實作與 live 落地紀錄。 |

## Exposure

目前實際使用的 exposure 基底已移到 `monitoring-rebuild/`：

- `monitoring-rebuild/10-victoria-metrics.yaml`
- `monitoring-rebuild/45-nvidia-device-plugin.yaml`
- `monitoring-rebuild/55-netdata.yaml`
- `monitoring-rebuild/60-netdata-child-stream-config.yaml`


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
| `ap-gateway.service` | AP Wi-Fi collector systemd service template。 |
| `ap-gateway.env.example` | AP Wi-Fi collector env 範例。 |
| `ap-snmp-gateway.service` | AP SNMP collector systemd service template。 |
| `ap-snmp-gateway.env.example` | AP SNMP collector env 範例。 |

## 注意事項

- 本層只提供 source/config；實際 kubeconfig、SSH key、API env 在 private handoff。
- 若實驗層需要 aggregator，應指向本層 `vm_aggregator.py`。
- `MONITORING_REBUILD_SOP.md` 是目前正式重建入口；本 README 只做目錄索引。


## RFSoC 重建步驟

目前主線已驗證的 RFSoC external monitoring 方案如下：

1. 在 RFSoC (`pynq`) 上確認 `node_exporter` 與 `netdata` 本機正常。
2. 由目前 control-plane / host 端以 Tailscale 連線 RFSoC：
   - scrape target：`100.91.37.32:9100`
   - SSH target：`xilinx@100.91.37.32`
3. 在 `vmagent` scrape config 中加入 `rfsoc4x2-node-exporter` job，labels 使用：
   - `access=tailscale`
   - `board=RFSoC4x2`
   - `node=rfsoc4x2-pynq`
4. 將 RFSoC Netdata child 的 `stream.conf` 指到目前 Netdata parent：
   - `destination = 140.113.179.9:32163`
   - `api key` 請從目前 live parent `/etc/netdata/stream.conf` 或私下交付資料取得，不寫入 repo
5. 在 host 端執行 `vm_agg_rfsoc.py`，目前建議直接使用本 repo 內已更新的預設值，或沿用 `collector_nodes.json` 內 `rfsoc4x2-pynq` 條目。

目前已驗證成功的關鍵端點：

- `VictoriaMetrics`: `http://140.113.179.9:31888`
- `Netdata parent`: `http://140.113.179.9:32163`
- `RFSoC node_exporter`: `100.91.37.32:9100`
- `RFSoC Netdata host`: `pynq`
- `RFSoC SSH`: `xilinx@100.91.37.32`


## 目前建議常駐方式

目前 host-side 正式重建路徑以 `systemd` 為主：

- `autoscale-api.service`
- `ap-gateway.service`
- `ap-snmp-gateway.service`

`tmux` 僅保留作為暫時除錯或手動 smoke test 方式，不再是建議的正式重建流程。
