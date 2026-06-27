# LLM Workload Monitoring Implementation Log

Date: 2026-06-25
Workspace: `/home/icclz2/Pre6G`
Feature: `Gemma 4 vLLM Serving Workload Monitoring`

## Scope

本次第一版工作目標是把 `vLLM` 視為獨立 workload 接入既有監控鏈路，而不改寫既有 node-centric schema：

- `vmagent -> VictoriaMetrics` 保留為唯一 time-series backbone
- `autoscale_api` 新增 workload-level 聚合
- `cluster-dashboard` 新增 workload table
- 不修改既有 `NodeStatusService` / `FullMetricsService` 的 node 職責

## Repo Changes

### Monitoring scrape

已新增 / 調整：

- `monitoring-rebuild/20-vmagent.yaml`
- `k3s-migration-bundle-sanitized/monitoring/scrape.yml`
- `k3s-migration-bundle-sanitized/monitoring/vmagent-config-gpu-1s.yaml`
- `k3s-migration-bundle-sanitized/monitoring/vmagent-config-auto-discovery.yaml`

新增 `vllm-serving-pods` scrape job：

- namespace: `ai-serving`
- discovery: `role: pod`
- scrape interval: `1s`
- metrics path: `/metrics`
- 僅保留 port name 符合 `.*metrics.*`
- 自動附加：
  - `kubernetes_namespace`
  - `kubernetes_pod`
  - `kubernetes_node`
  - `kubernetes_container`

### API / aggregation

已新增：

- `autoscale_api/app/schemas/workload.py`
- `autoscale_api/app/adapters/vllm_workload_adapter.py`
- `autoscale_api/app/services/workload_status_service.py`
- `autoscale_api/app/routers/workloads.py`

已調整：

- `autoscale_api/app/main.py`
- `autoscale_api/app/adapters/k8s_adapter.py`
- `deploy/k3s/autoscale-api-rbac.yaml`

新增 API：

- `GET /api/v1/workloads`
- `GET /api/v1/workloads/{namespace}/{workload}/status`
- `GET /api/v1/nodes/{node_name}/workloads`

目前 workload identity 組成：

- `namespace`
- `Deployment` name
- `model_name`

其中 `Deployment` 由 `Pod -> ownerReferences -> ReplicaSet -> Deployment` 解析。

### Dashboard

已調整：

- `cluster-dashboard/src/App.tsx`

新增 `LLM Serving Lab` observation-oriented 視圖，顯示：

- `Service Overview`
- `Live Serving Observation`
- `Replica / Kubernetes Observation`

這一版刻意只顯示客觀觀測資料，不顯示：

- capacity score
- remaining GPU capacity
- scheduler recommendation
- `AVAILABLE / CAUTION / SATURATED`

## Live Validation

### Cluster preflight

已確認：

- `iccl-s3-251230` 具 `nvidia.com/gpu: 1`
- 該卡由 `dcgm-exporter` 回報為 `RTX 4090 24GB`
- `ai-serving` namespace 可用 `local-path` PVC

### vLLM serving deployment

已新增：

- `k3s-migration-bundle-sanitized/llm-serving/gemma4-e2b-w4a16/namespace.yaml`
- `pvc.yaml`
- `deployment.yaml`
- `service.yaml`
- `benchmark-job.yaml`

實際落地重點：

- image: `vllm/vllm-openai:v0.23.0`
- runtime class: `nvidia`
- node selector: `iccl-s3-251230`
- model: `unsloth/gemma-4-E2B-it-qat-w4a16`
- served model name: `gemma4-e2b-w4a16`
- service port name: `http-metrics`
- live workload query window: `60s`

### Cold-start fixes found during live deploy

實際部署過程中確認了兩個 manifest 細節必須修正：

1. 需要 `runtimeClassName: nvidia`
   - 否則 Pod 雖申請 GPU，container 內仍可能看不到完整 NVIDIA runtime
2. 需要 `startupProbe`
   - Gemma 4 cold start 需要數十秒到數分鐘
   - 若只有 aggressive readiness/liveness，會在 server 尚未 bind `:8000` 前被 kubelet 重啟
3. 單 GPU node 應使用 `strategy: Recreate`
   - 預設 rolling update 會先建立新 ReplicaSet pod
   - 在只有 1 張獨占 GPU 的情況下，更新時容易出現多餘 Pending pod

### Observed live metrics

已直接從 Pod `/metrics` 與 VictoriaMetrics 確認以下核心指標存在：

- `vllm:generation_tokens_total`
- `vllm:prompt_tokens_total`
- `vllm:num_requests_waiting`
- `vllm:kv_cache_usage_perc`

並觀察到 labels 包含：

- `model_name="gemma4-e2b-w4a16"`
- `engine="0"`
- 由 vmagent 補上的 `kubernetes_*` labels

因此第一版 adapter 的核心 metric 假設與 live export 一致。

另外已完成 live workload API smoke test：

- `GET /api/v1/workloads`
- `GET /api/v1/workloads/ai-serving/gemma4-e2b-vllm/status`

回應已可正確顯示：

- `runtime = vllm`
- `workload = gemma4-e2b-vllm`
- `model_name = gemma4-e2b-w4a16`
- `ready_replicas = 1`

在成功送出多個 `chat/completions` request 後，已實際觀察到：

- Pod 內 counter 從 `prompt=54 / generation=240` 增加到 `prompt=139 / generation=840`
- VictoriaMetrics `rate(vllm:generation_tokens_total[60s]) = 10`
- VictoriaMetrics `rate(vllm:prompt_tokens_total[60s]) = 1.4166666666666667`
- workload API 同步回傳：
  - `generation_tokens_per_second = 10.0`
  - `prompt_tokens_per_second = 1.4166666666666667`

## Tests

已完成：

- `python -m unittest discover -s autoscale_api/tests`
- `python3 -m compileall autoscale_api/app`
- `cluster-dashboard` 以 Node 22 成功 `npm run build`

## Remaining Follow-ups

以下項目不阻塞第一版 merge，但仍建議補做：

1. 以 rebuilt image/manifest 正式更新 cluster 內 dashboard deployment
2. 持續觀察 `benchmark-job.yaml` 長一點時間下的 queue/KV 變化
3. 若未來擴成多 replica，補 scheduler / placement 端對 workload API 的實際消費
