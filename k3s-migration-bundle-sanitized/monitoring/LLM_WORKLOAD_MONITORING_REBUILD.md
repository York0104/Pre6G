# LLM Workload Monitoring Rebuild

Date: 2026-06-25
Target workload: `Gemma 4 vLLM`

## Goal

在不改動既有 node monitoring schema 的前提下，把 `vLLM` serving workload 接入：

- `vmagent`
- `VictoriaMetrics`
- `autoscale_api`
- `cluster-dashboard`

## Applied Monitoring Changes

已在下列檔案加入 `vllm-serving-pods` scrape job：

- `monitoring-rebuild/20-vmagent.yaml`
- `scrape.yml`
- `vmagent-config-gpu-1s.yaml`
- `vmagent-config-auto-discovery.yaml`

已在下列檔案加入 `autoscale-api-llamacpp-benchmark` scrape job：

- `vmagent-config-gpu-1s.yaml`
- `vmagent-config-auto-discovery.yaml`

設計重點：

- `role: pod` 自動發現
- namespace 鎖定 `ai-serving`
- container port 名稱匹配 `.*metrics.*`
- `1s` scrape interval
- 保留 Kubernetes 自動 discovery labels，不要求 workload 額外手寫一批自訂 labels
- `llama.cpp offline benchmark` 不直接 scrape benchmark target pod，而是 scrape `autoscale_api /metrics`
- `autoscale_api /metrics` 暴露 `run lifecycle` 與 `final throughput result`
- `vmagent` 對 `autoscale-api` 採 `1s` scrape interval，讓 `VictoriaMetrics` 可與 `DCGM` / `node-exporter` 對齊 benchmark active window

## Live Deployment Notes

實測落地 manifest 在：

- `../llm-serving/gemma4-e2b-w4a16/namespace.yaml`
- `../llm-serving/gemma4-e2b-w4a16/pvc.yaml`
- `../llm-serving/gemma4-e2b-w4a16/deployment.yaml`
- `../llm-serving/gemma4-e2b-w4a16/service.yaml`

實測過程中需要的修正：

- `runtimeClassName: nvidia`
- `startupProbe` for model cold start
- `strategy: Recreate` for single-GPU node rollout

## Verified Metrics

已從 live Pod `/metrics` 與 VictoriaMetrics label list 確認：

- `vllm:generation_tokens_total`
- `vllm:prompt_tokens_total`
- `vllm:num_requests_waiting`
- `vllm:kv_cache_usage_perc`

輔助 latency / queue / request histogram 系列也已進 VM，可供後續擴充 workload adapter。

## First-Version Caveats

1. 第一次 cold start 仍會花較長時間下載與編譯模型
2. 單 GPU node 更新時應避免 rolling update
3. live `autoscale_api` 目前以 `PRE6G_WORKLOAD_QUERY_WINDOW_SECONDS=10` 運行，讓 `LLM Serving Lab` 更容易觀察單次 inference 與短時間 benchmark 的 throughput 變化
4. `benchmark-job.yaml` 目前預設排到 `icclz2`，以縮短 image pull 與啟動等待
5. dashboard 視覺化仍保留後續討論空間，這一輪先完成 backend/live integration
