# 4090 Offline Throughput Benchmark Target

本文件定義 `LLM Serving Lab` 中 `Offline Throughput Benchmark` 的建議正式路徑：在支援 `vLLM` 的 `RTX 4090` 節點上，建立 dedicated benchmark target。

## 設計目標

將 `Hardware Capacity View` 與 live `Serving Capacity View` 分開：

- `Serving Benchmark`
  - official tool: `vllm bench serve`
  - target: live `Gemma 4` serving pod
- `Offline Throughput Benchmark`
  - official tool: `vllm bench throughput`
  - target: dedicated `RTX 4090` benchmark pod

## 建議節點

- node: `iccl-s3-251230`
- GPU: `NVIDIA GeForce RTX 4090`

## 建議 target

建議 manifest：

- [deploy/k3s/llm-offline-bench-4090.example.yaml](../deploy/k3s/llm-offline-bench-4090.example.yaml)

設計原則：

- dedicated pod
- 不對外提供 API
- 容器常駐 `sleep infinity`
- 由 `autoscale_api` 用 `kubectl exec` 進去跑 `vllm bench throughput`

## 建議模型方向

若目標是和現有 live serving 對齊，第一版建議沿用：

- `unsloth/gemma-4-E2B-it-qat-w4a16`

## 主要代價

### 1. GPU 佔用代價

dedicated offline target 會吃掉整張 `4090`：

- `nvidia.com/gpu: 1`

這表示在單卡情況下，該 node 不能同時再排 live `Gemma 4` serving pod。

### 2. 切換代價

若只有一張 `4090`，要在 live serving 與 offline throughput 間切換，必須：

1. 停掉 live `vllm serve`
2. 啟動 dedicated offline benchmark target
3. 執行 `vllm bench throughput`
4. 刪除 offline target
5. 重新啟動 live serving

這會帶來：

- model reload
- cold start / warm-up
- service unavailable window

### 3. 服務中斷代價

benchmark 期間若同一張卡原本用於對外 serving，則 live API 會暫時不可用。

## 建議操作模式

### 模式 A：分時切換

- 平時：保留 live `Gemma 4` serving
- benchmark 時：短暫切到 dedicated offline target
- 跑完後：恢復 live serving

### 模式 B：額外支援 GPU

若未來有第二張受支援 GPU，則可：

- 一張跑 live serving
- 一張跑 offline throughput

## autoscale_api 建議設定

只有在你真的要啟用 offline benchmark 時，才設定：

- `PRE6G_LLM_OFFLINE_BENCH_NAMESPACE=ai-serving`
- `PRE6G_LLM_OFFLINE_BENCH_TARGET=deploy/gemma4-offline-bench-4090`

## 平台結論

目前最合理、最符合平台設計的 offline throughput target 是：

- `RTX 4090 dedicated benchmark pod`

而不是：

- `GTX 1080 Ti`
- 或把 `vllm bench throughput` 硬塞進正在 serving 的 live pod
