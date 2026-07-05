# icclz1 Offline Throughput Benchmark Validation Record

> 2026-07-04 update:
> `GTX 1080 Ti` 的正式 offline benchmark 路徑已改為 `llama.cpp + llama-bench`。
> 本文件保留的是先前 `vLLM bench throughput` 在 Pascal 上失敗的驗證紀錄。
> 新的正式設計請改看 [LLAMACPP_OFFLINE_BENCHMARK_1080TI.md](./LLAMACPP_OFFLINE_BENCHMARK_1080TI.md)。

本文件記錄 `LLM Serving Lab` 內 `Offline Throughput Benchmark` 在 `icclz1` / `GTX 1080 Ti` 上的實測結果與支援結論。

## 驗證目標

曾嘗試將 `vllm bench throughput` 從 live `Gemma 4` serving pod 分離，改在 `icclz1` 上使用 dedicated GPU target。

理由：

- `vllm bench serve` 量測的是既有 live serving endpoint。
- `vllm bench throughput` 量測的是 offline batch inference throughput。
- `vllm bench throughput` 會在執行位置自行初始化新的 `LLM` engine。
- 若直接在目前 live `Gemma 4` pod 內執行，會因為再啟一個 engine 而撞上 VRAM 上限。

## 驗證節點

- node: `icclz1`
- GPU: `NVIDIA GeForce GTX 1080 Ti`
- VRAM: `11 GiB`

## 驗證過的模型方向

- model: `Qwen/Qwen2.5-1.5B-Instruct`
- engine: `vllm bench throughput --backend vllm`

當時選這個方向的原因是：

- 1.5B 級模型比目前 live `Gemma 4 E2B` 更適合 11GB VRAM。
- 避開 `AWQ` 在 Pascal 世代 GPU 上的額外支援限制。
- 官方 Qwen 系列模型可直接配合 vLLM 使用。

## 驗證時使用的 benchmark 參數

repo 內目前固定 profile：

- `Offline Smoke`
  - `input_len=128`
  - `output_len=64`
  - `num_prompts=16`
  - `gpu_memory_utilization=0.72`
  - `max_model_len=2048`
- `Offline Steady`
  - `input_len=384`
  - `output_len=128`
  - `num_prompts=48`
  - `gpu_memory_utilization=0.72`
  - `max_model_len=2048`

這些值當時的設計目標是：

- 先在 11GB 卡上穩定跑通。
- 保留足夠 VRAM headroom，降低初始化失敗機率。
- 先建立可重現的 `hardware capacity view`，再逐步往上調。

## Kubernetes 驗證路徑

驗證時曾使用：

- [deploy/k3s/llm-offline-bench-icclz1.example.yaml](../deploy/k3s/llm-offline-bench-icclz1.example.yaml)

這個 pod 的角色不是提供 API，而是提供一個可被 `autoscale_api` 用 `kubectl exec` 進去執行 benchmark 的 GPU 容器。

設計重點：

- 固定排到 `icclz1`
- 掛載 Hugging Face cache
- 容器常駐 `sleep infinity`
- `autoscale_api` 再於其中執行 `vllm bench throughput`

驗證時 `autoscale_api` 曾使用：

- `PRE6G_LLM_OFFLINE_BENCH_NAMESPACE=ai-serving`
- `PRE6G_LLM_OFFLINE_BENCH_TARGET=deploy/qwen25-3b-awq-offline-bench`

## Host-side 備案

若未來不想經 Kubernetes，也可考慮 host-side 路徑：

- 直接在 `icclz1` host 或專用 container 執行 `vllm bench throughput`
- 再由獨立 controller 或 SSH runner 呼叫

但目前 repo 內已接通的是 `kubectl exec` 路徑，因此第一版建議先維持 Kubernetes target。

## 驗證結論

截至 `2026-07-02`，`GTX 1080 Ti` 已被排除為目前平台下的受支援 `vLLM Offline Throughput Benchmark` target。

原因：

- `GTX 1080 Ti` 為 Pascal，`compute capability = 6.1`
- `vLLM` 官方支援下限高於 Pascal 世代
- `AWQ` 模型已實測不相容
- 即使改為非 AWQ 較小模型，`vllm/vllm-openai:v0.23.0` 仍在 benchmark target 內出現 CUDA 初始化錯誤：
  - `Error 804: forward compatibility was attempted on non supported HW`

因此目前應明確解讀為：

- control path 已驗證打通
- 但 `icclz1` / `GTX 1080 Ti` 不在目前支援邊界
- 此 node 不應繼續作為正式 `Offline Throughput Benchmark` 候選節點

## 解讀邊界

若未來改在其他受支援 GPU 上重新啟用 `Offline Throughput Benchmark`，其結果應解讀為：

- 比較偏向 `Hardware Capacity View`
- 適合與 `Serving Benchmark` 對照
- 不直接等於 live OpenAI-compatible API serving capacity

若 `icclz1` 還同時有其他 GPU pod，且使用的是 `nvidia.com/gpu.shared: 1`，結果會反映共享環境，而不是乾淨單卡峰值。

## 2026-07-02 實際驗證結果

本輪已完成以下 live 驗證：

- dedicated target pod 已成功部署到 `icclz1`
- host-side `autoscale_api` 已實際對該 pod 發出 `POST /api/v1/llm-lab/offline-throughput`
- `autoscale_api -> kubectl exec -> benchmark target` 路徑已確認打通

目前實際 blocker：

- `vllm/vllm-openai:v0.23.0` container 在 `GTX 1080 Ti` 上會出現 CUDA 初始化錯誤
- 錯誤關鍵字：`Error 804: forward compatibility was attempted on non supported HW`

因此目前狀態應解讀為：

- benchmark control path：已部署、已打通
- `icclz1` GPU benchmark execution：被目前 container runtime / Pascal GPU 相容性卡住

目前平台結論：

- `1080 Ti` 從正式 offline throughput target 候選中排除
- 後續若要恢復 offline throughput，應改在 `CC >= 7.0`，實務上建議 `CC >= 7.5` 的 GPU 節點上驗證
