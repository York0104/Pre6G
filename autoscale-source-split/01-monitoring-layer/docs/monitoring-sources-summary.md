# Monitoring Sources Summary

Date: 2026-07-08
Workspace: `/home/icclz2/Pre6G`
Scope: `autoscale-source-split/01-monitoring-layer`

## Monitoring Sources

| Source | Kind | How it enters this layer | Representative metrics / signals | Configured scrape or update interval | Live status |
| --- | --- | --- | --- | --- | --- |
| `dcgm-exporter` | GPU exporter | `vmagent -> VictoriaMetrics -> vm_aggregator.py` | `DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_FB_USED` | `1s` in [monitoring-rebuild/20-vmagent.yaml](/home/icclz2/Pre6G/monitoring-rebuild/20-vmagent.yaml:33) | Live and queryable |
| `node-exporter` | Node exporter | `vmagent-node-local -> VictoriaMetrics -> vm_aggregator.py` | `node_cpu_seconds_total`, `node_filesystem_*`, `node_network_*` | global `10s` in [monitoring-rebuild/20-vmagent.yaml](/home/icclz2/Pre6G/monitoring-rebuild/20-vmagent.yaml:105) | Live and queryable |
| `kubelet / cAdvisor` | K8s node / container metrics | `vmagent-node-local -> VictoriaMetrics -> vm_aggregator.py` | `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes` | global `10s` in [monitoring-rebuild/20-vmagent.yaml](/home/icclz2/Pre6G/monitoring-rebuild/20-vmagent.yaml:105) | Live and queryable |
| `kube-state-metrics` | K8s object-state exporter | `vmagent -> VictoriaMetrics -> vm_aggregator.py` | `kube_pod_info`, `kube_pod_status_phase`, `kube_node_status_*` | global `10s` in [monitoring-rebuild/20-vmagent.yaml](/home/icclz2/Pre6G/monitoring-rebuild/20-vmagent.yaml:20) | Live and queryable |
| `vmagent-self` | Scrape pipeline self metrics | `vmagent -> VictoriaMetrics` | `up{job="vmagent-self"}` and vmagent self metrics | global `10s` in [monitoring-rebuild/20-vmagent.yaml](/home/icclz2/Pre6G/monitoring-rebuild/20-vmagent.yaml:20) | Live and queryable |
| `vLLM pod metrics` | Workload exporter | `vmagent -> VictoriaMetrics` | `vllm:generation_tokens_total`, `vllm:prompt_tokens_total` | `1s` in [monitoring-rebuild/20-vmagent.yaml](/home/icclz2/Pre6G/monitoring-rebuild/20-vmagent.yaml:54) | Live and queryable |
| `Netdata parent` | Node + host-scoped metrics API | `Netdata API -> vm_aggregator.py` or `vm_agg_rfsoc.py` | `netdata_info`, `system.cpu`, `system.ram`, `system.io` | `update_every: 1` for kubelet / kubeproxy / k8s-state collectors in [netdata-default-values.yaml](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/netdata-default-values.yaml:342) and [netdata-default-values.yaml](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/netdata-default-values.yaml:502) | Live and queryable |
| `RFSoC node-exporter` | External node exporter | `vmagent -> VictoriaMetrics -> vm_agg_rfsoc.py` | `node_cpu_seconds_total`, `node_filesystem_*`, `node_network_*` | global `10s` in [monitoring-rebuild/20-vmagent.yaml](/home/icclz2/Pre6G/monitoring-rebuild/20-vmagent.yaml:20), target in [monitoring-rebuild/20-vmagent.yaml](/home/icclz2/Pre6G/monitoring-rebuild/20-vmagent.yaml:82) | Config exists, no live samples seen during this measurement |
| `RFSoC Netdata` | External node Netdata stream | `Netdata parent mirrored host -> vm_agg_rfsoc.py` | `netdata_info`, `system.cpu`, `system.ram`, `system.io` for host `pynq` | effectively `~1s` update cadence observed via parent mirror | Live and queryable |
| `RFSoC PYNQ / XRT SSH status` | Out-of-band device status | `SSH -> vm_agg_rfsoc.py` | `/run/rfsoc_overlay_status.json`, XRT / overlay state | on-demand per aggregator run; SSH timeout `3s` in [vm_agg_rfsoc.py](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/vm_agg_rfsoc.py:27) | Not part of vmagent scrape |
| `AP Wi-Fi collector` | Custom collector | `SSH -> ap_gateway.py -> VictoriaMetrics -> vm_agg_ap_gateway.py` | `ap_wifi_station_count`, `ap_wifi_station_tx_bytes`, `ap_wifi_station_signal_dbm` | producer interval `10s` in [ap_gateway.py](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/ap_gateway/ap_gateway.py:14) | Config/code exists, no live samples seen during this measurement |
| `AP SNMP collector` | Custom collector | `SNMP -> ap_snmp_gateway.py -> VictoriaMetrics -> vm_agg_ap_gateway.py` | `ap_node_cpu_usage_percent`, `ap_node_memory_*`, `ap_node_iface_*` | producer interval `10s` in [ap_snmp_gateway.py](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/ap_gateway/ap_snmp_gateway.py:17) | Config/code exists, no live samples seen during this measurement |
| `VictoriaMetrics query service` | Time-series store / query backbone | queried directly by all aggregators | `/api/v1/query`, `/api/v1/import/prometheus` | not a scrape source itself | Live and queryable |
| `VictoriaMetrics self metrics` | Self metrics | not configured in this repo's active `scrape.yml` | N/A | no active scrape job found in this layer | Not currently part of this measured pipeline |

## Live Scrape / Lag Measurement

Measurement date: 2026-07-08

Method:

- `VictoriaMetrics`-backed sources: sampled `max(timestamp(metric))` once per second for `20s~30s`.
- `Netdata`: sampled `netdata_info` exposition timestamps once per second for `20s`.
- `lag` means `probe_time - latest_sample_timestamp`.
- For multi-node jobs, `mean_update_s` is based on the freshest visible sample in the queried fleet, so it can look shorter than the configured scrape interval when different nodes update out of phase.

| Source | Probe metric | Config interval | Measured mean lag | Measured p50 lag | Measured max lag | Observed mean update step | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `dcgm-exporter` | `DCGM_FI_DEV_GPU_UTIL` | `1s` | `3.506s` | `3.288s` | `4.321s` | `1.154s` | Matches expected low-latency GPU path |
| `node-exporter` | `node_cpu_seconds_total{job="node-exporter",mode!="idle"}` | `10s` | `4.185s` | `4.168s` | `5.700s` | `2.000s` | Update step is shortened by cross-node staggering; configured scrape is still `10s` |
| `kubelet / cAdvisor` | `container_cpu_usage_seconds_total{job="kubelet-cadvisor",container!=""}` | `10s` | `4.206s` | `4.197s` | `5.638s` | `2.000s` | Same cross-node staggering effect as node-exporter |
| `kube-state-metrics` | `kube_pod_info` | `10s` | `8.229s` | `8.271s` | `12.763s` | `10.000s` | Stable 10-second class state metrics |
| `vmagent-self` | `up{job="vmagent-self"}` | `10s` | `8.915s` | `8.978s` | `13.831s` | `10.000s` | Good proxy for scrape-pipeline self freshness |
| `vLLM pod metrics` | `vllm:generation_tokens_total` | `1s` | `3.471s` | `3.268s` | `4.293s` | `1.333s` | Consistent with prior workload live-observation notes |
| `Netdata parent` | `netdata_info` timestamp | `~1s` | `~0.000s` | `-0.001s` | `0.000s` | `1.076s` | Essentially real-time; tiny negative lag is clock skew / timestamp rounding |
| `Netdata mirrored host icclz2` | `netdata_info` timestamp | `~1s` | `-0.005s` | `-0.005s` | `-0.002s` | `1.076s` | Same as above |
| `Netdata mirrored host pynq` | `netdata_info` timestamp | `~1s` | `-0.052s` | `-0.049s` | `-0.039s` | `1.077s` | RFSoC Netdata mirror is live; small negative lag suggests clock skew |
| `RFSoC node-exporter` | `node_cpu_seconds_total{job="rfsoc4x2-node-exporter",mode!="idle"}` | `10s` | N/A | N/A | N/A | N/A | No live samples returned during this measurement window |
| `AP SNMP collector` | `ap_node_cpu_usage_percent` | `10s` | N/A | N/A | N/A | N/A | No live samples returned during this measurement window |
| `AP Wi-Fi collector` | `ap_wifi_station_count` | `10s` | N/A | N/A | N/A | N/A | No live samples returned during this measurement window |
| `VictoriaMetrics self metrics` | N/A | N/A | N/A | N/A | N/A | N/A | No active scrape job found in current `scrape.yml` |

## Takeaways

- 目前 live 上最即時的鏈路是 `dcgm-exporter`、`vLLM metrics`、`Netdata`。
- `kube-state-metrics` 與 `vmagent-self` 明顯屬於 `10s` 級資料，較適合 cluster state / health 觀察。
- `node-exporter` 與 `kubelet/cAdvisor` 的全域最新樣本 lag 目前約 `4~6s`，但這不代表 scrape 已改成 `2s`；它只是多節點 target 交錯更新後，`max(timestamp(...))` 看起來更密。
- `RFSoC node-exporter` 與 `AP gateway` 類 metrics 在這次量測時沒有 live sample，表示不是目前沒在送，就是 label / target 和現在的 live 環境不一致，若要納入正式面板，建議下一步先做 target health 檢查。
