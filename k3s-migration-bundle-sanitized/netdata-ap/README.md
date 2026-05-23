# Netdata / AP

本資料夾保存 Netdata values 與 AP monitoring helpers。

| 檔案/目錄 | 說明 |
| --- | --- |
| `helm-values-netdata.current.yaml` | 來源 cluster 匯出的 Netdata Helm values。 |
| `netdata-default-values.yaml` | 1 秒 kubelet cAdvisor collection 用 values 參考。 |
| `netdata-nodeport.yaml` | Netdata NodePort exposure manifest。 |
| `netdata-snmp-openwrt.current.yaml` | OpenWrt AP SNMP ConfigMap 匯出。 |
| `ap_gateway/` | SSH/SNMP AP gateway collector 與設計文件。 |
| `vm_agg_ap_gateway.py` | 使用 VictoriaMetrics/AP gateway metrics 的 AP aggregator。 |

目前 AP SNMP target 為 `192.168.1.1`，community 為 `public`。AP SSH key 不在 sanitized copy；請透過 private handoff 恢復為 `~/.ssh/openwrt_ap_ed25519` 或設定 `SSH_KEY`。
