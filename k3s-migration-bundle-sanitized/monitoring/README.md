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
| `LLM_WORKLOAD_MONITORING_REBUILD.md` | Gemma 4 vLLM workload 監控第一版重建與落地紀錄。 |
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

若已啟用 LLM workload 監控，還應可看到：

- vmagent `vllm-serving-pods` target
- vmagent `autoscale-api-llamacpp-benchmark` target
- `vllm:generation_tokens_total`
- `vllm:prompt_tokens_total`
- `vllm:num_requests_waiting`
- `vllm:kv_cache_usage_perc`
- `pre6g_llamacpp_offline_benchmark_prompt_tps_mean`
- `pre6g_llamacpp_offline_benchmark_generation_tps_mean`
- `pre6g_llamacpp_offline_benchmark_live_prompt_tps`
- `pre6g_llamacpp_offline_benchmark_live_generation_tps`
- `pre6g_llamacpp_offline_benchmark_live_pg_tps`

## llama.cpp Offline Benchmark PromQL

以下查詢可直接用於 `GTX 1080 Ti llama.cpp offline benchmark` 與 `DCGM` 對齊觀察：

### 1. Benchmark active window

```promql
pre6g_llamacpp_offline_benchmark_run_active{runtime="llamacpp", namespace="ai-serving"}
```

### 2. Latest prompt throughput

```promql
pre6g_llamacpp_offline_benchmark_prompt_tps_mean{runtime="llamacpp", namespace="ai-serving"}
```

### 2b. Live rolling prompt throughput

```promql
pre6g_llamacpp_offline_benchmark_live_prompt_tps{runtime="llamacpp", namespace="ai-serving"}
```

### 3. Latest generation throughput

```promql
pre6g_llamacpp_offline_benchmark_generation_tps_mean{runtime="llamacpp", namespace="ai-serving"}
```

### 3b. Live rolling generation throughput

```promql
pre6g_llamacpp_offline_benchmark_live_generation_tps{runtime="llamacpp", namespace="ai-serving"}
```

### 4. Latest prompt+generation throughput

```promql
pre6g_llamacpp_offline_benchmark_prompt_generation_tps_mean{runtime="llamacpp", namespace="ai-serving"}
```

### 4b. Live rolling prompt+generation throughput

```promql
pre6g_llamacpp_offline_benchmark_live_pg_tps{runtime="llamacpp", namespace="ai-serving"}
```

### 5. GPU contention preflight

```promql
pre6g_llamacpp_offline_benchmark_gpu_contended{runtime="llamacpp", namespace="ai-serving"}
```

### 6. 與 DCGM GPU util 對齊

```promql
DCGM_FI_DEV_GPU_UTIL{kubernetes_node="icclz1"}
```

搭配：

```promql
pre6g_llamacpp_offline_benchmark_run_active{node_name="icclz1"}
```

就能在 Grafana 上看出：

- benchmark 何時開始/結束
- benchmark active window 期間 GPU util 是否同步升高
- 完成後 final throughput 結果是多少
