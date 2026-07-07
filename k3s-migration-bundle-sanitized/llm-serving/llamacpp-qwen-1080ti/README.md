# llama.cpp Offline Throughput Benchmark for GTX 1080 Ti

這個目錄保存 `GTX 1080 Ti / Pascal SM61` 的第一版 `llama.cpp` offline throughput benchmark 材料。

## Purpose

- runtime: `llama.cpp`
- benchmark mode: `offline`
- target GPU: `NVIDIA GeForce GTX 1080 Ti`
- target node: `icclz1`
- main goal: 建立 Pascal 舊卡的 `Hardware Capacity View`

這條路徑刻意與目前 `RTX 4090 + vLLM live serving` 分離：

- `vLLM` 保留在 `Serving Capacity View`
- `llama.cpp + llama-bench` 用於 `Offline Hardware Throughput View`

## Files

- `Dockerfile.cuda118-sm61`
- `profiles.json`
- `benchmark-target.yaml`
- `build_and_import_to_icclz1.sh`

## Build Metadata

- CUDA: `11.8`
- `CMAKE_CUDA_ARCHITECTURES=61`
- `GGML_CUDA=ON`
- `GGML_NATIVE=OFF`
- pinned llama.cpp ref:
  - tag/ref: `b9870`
  - commit: `2d97363`

## Fixed Model

- model family: `Gemma 4 E2B IT`
- format: `GGUF`
- quantization: `Q4_K_M`
- suggested source: `unsloth/gemma-4-E2B-it-GGUF`
- fixed filename: `gemma-4-E2B-it-Q4_K_M.gguf`
- fixed in-container path: `/models/gemma/gemma-4-E2B-it-Q4_K_M.gguf`
- host path on `icclz1`: `/var/lib/pre6g/models/gemma-4-e2b-it-gguf`
- sha256: `9378bc471710229ef165709b62e34bfb62231420ddaf6d729e727305b5b8672d`

正式跑 benchmark 前，請確認 manifest / runtime env / autoscale_api env / benchmark result metadata 使用同一個模型檔與 checksum。


## Why `CMAKE_CUDA_ARCHITECTURES=61`

`GTX 1080 Ti` 是 Pascal，`compute capability = 6.1`。

本 image 明確針對：

- `sm61`

編譯 `llama.cpp` CUDA backend，避免沿用只針對較新 GPU 的預設編譯組態。

## Build

```bash
cd /home/icclz2/Pre6G/k3s-migration-bundle-sanitized/llm-serving/llamacpp-qwen-1080ti
docker build \
  -f Dockerfile.cuda118-sm61 \
  --build-arg LLAMA_CPP_REF=b9870 \
  -t pre6g/llamacpp-cuda118-sm61:gemma4-e2b-q4km \
  .
```

目前這顆 image 需要為 Gemma build/import 到 `icclz1`：

- image: `pre6g/llamacpp-cuda118-sm61:gemma4-e2b-q4km`

注意：

- `benchmark-target.yaml` 使用 `imagePullPolicy: Never`，避免 K3s 嘗試從 Docker Hub 拉取 `docker.io/pre6g/...`。
- 因此 image 必須先存在於 `icclz1` 的 k3s/containerd runtime。
- 在沒有 NVIDIA runtime 的普通 `docker run` 下，`llama-bench` 會因為缺少 `libcuda.so.1` 而無法啟動。
- 這是預期行為；正式 target pod 會透過 `runtimeClassName: nvidia` 注入 driver libraries。

## Build And Import To `icclz1`

若目前 Harbor 不可用，可直接使用互動式 helper：

```bash
cd /home/icclz2/Pre6G/k3s-migration-bundle-sanitized/llm-serving/llamacpp-qwen-1080ti
chmod +x build_and_import_to_icclz1.sh
./build_and_import_to_icclz1.sh
```

預設會：

- 重新 build image
- 將 image 經 `gzip` 後透過 `ssh` 串流到 `icclz1`
- 在 `icclz1` 執行 `sudo k3s ctr images import -`

若 image 已在本機 build 完成，可略過 build：

```bash
SKIP_BUILD=1 ./build_and_import_to_icclz1.sh
```

若 ssh target 不是預設值，可改用：

```bash
REMOTE_SSH_TARGET="icclz1@icclz1" ./build_and_import_to_icclz1.sh
```

## Deploy Target Pod

```bash
kubectl apply -f benchmark-target.yaml
kubectl -n ai-serving get pod -l app=llamacpp-gemma4-e2b-q4km-bench -o wide
```

在 apply 前，請先確認 `icclz1` 已有模型檔：

```text
/var/lib/pre6g/models/gemma-4-e2b-it-gguf/gemma-4-E2B-it-Q4_K_M.gguf
```

Pod 內掛載位置為：

```text
/models/gemma/gemma-4-E2B-it-Q4_K_M.gguf
```

這個 Deployment 是長駐 benchmark environment；啟動時只會 `sleep infinity`，正式測試需透過 `kubectl exec` 手動執行 `llama-bench`。

## Smoke Validation

```bash
kubectl -n ai-serving exec deploy/llamacpp-gemma4-e2b-q4km-bench -- nvidia-smi
kubectl -n ai-serving exec deploy/llamacpp-gemma4-e2b-q4km-bench -- llama-bench --list-devices
kubectl -n ai-serving exec deploy/llamacpp-gemma4-e2b-q4km-bench -- /bin/bash -lc '\
  /usr/local/bin/llama-bench \
    -m /models/gemma/gemma-4-E2B-it-Q4_K_M.gguf \
    -ngl 999 \
    -p 512 \
    -n 128 \
    -r 3'
```

目前 image 只包含 `llama-bench`，不包含 `llama-cli` 或 `llama-server`；它是 offline benchmark target，不是互動式聊天或 OpenAI-compatible serving runtime。

## Metrics Semantics

- `Prompt TPS` = llama-bench `pp` mean tokens/s
- `Generation TPS` = llama-bench `tg` mean tokens/s
- `Prompt + Generation TPS` = llama-bench `pg` mean tokens/s
- `Waiting Requests` = `N/A — offline benchmark`
- `KV Cache Usage` = `N/A — offline benchmark`
- `Result Freshness` = benchmark completion age

## VictoriaMetrics Bridge

這條 `llama.cpp offline benchmark` 不是長駐 serving runtime，因此不會像 `vLLM` 一樣原生暴露 `/metrics`。

目前採用的 bridge 是：

```text
llama-bench run state / final result
-> autoscale_api /metrics
-> vmagent 1s scrape
-> VictoriaMetrics
```

已暴露的 Prometheus metrics 包括：

- `pre6g_llamacpp_offline_benchmark_run_active`
- `pre6g_llamacpp_offline_benchmark_run_status{state=...}`
- `pre6g_llamacpp_offline_benchmark_run_started_timestamp_seconds`
- `pre6g_llamacpp_offline_benchmark_run_completed_timestamp_seconds`
- `pre6g_llamacpp_offline_benchmark_run_elapsed_seconds`
- `pre6g_llamacpp_offline_benchmark_result_duration_seconds`
- `pre6g_llamacpp_offline_benchmark_result_freshness_seconds`
- `pre6g_llamacpp_offline_benchmark_prompt_tps_mean`
- `pre6g_llamacpp_offline_benchmark_generation_tps_mean`
- `pre6g_llamacpp_offline_benchmark_prompt_generation_tps_mean`
- `pre6g_llamacpp_offline_benchmark_gpu_preflight_process_count`
- `pre6g_llamacpp_offline_benchmark_gpu_contended`

注意：

- 這些 metrics 會保存 `run lifecycle` 與 `final benchmark result`
- active run 期間，`autoscale_api` 會以 `llama-bench --progress --output jsonl` 逐段解析 `pp / tg / pg` 結果，輸出執行中的 live sample
- `Live Rolling Throughput` 代表 active run 中最近一次已解析的 `pp / tg / pg` live sample 與 timeline
- `Final Benchmark Result` 則保留正式 completed result 與 latest completed-step throughput
- 這仍不是 token-by-token stream；它是 `llama-bench` 在單次執行過程中逐段吐出的 live benchmark sample

## 2026-07-05 Measured Baseline

以下 baseline 是此 1080 Ti llama.cpp benchmark target 的既有歷史結果，模型為切換 Gemma 前的舊固定模型；Gemma 需要重新跑一輪後再更新正式數字。

本 image 與 target pod 已完成 live cluster 驗證。

已確認打通：

- `autoscale_api`
- `kubectl exec`
- `llama-bench`
- JSON parser
- dashboard `Offline Hardware Benchmark`

實測結果：

| Profile | Run ID | Duration | Prompt TPS (`pp`) | Generation TPS (`tg`) | Prompt + Generation TPS (`pg`) | GPU Preflight |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `pascal-smoke` | `llamacpp-pascal-smoke-run-20260705T014938Z` | `5.0 sec` | `3356.873` | `161.313` | `443.227` | `Contended` |
| `pascal-continuous` | `llamacpp-pascal-continuous-run-20260705T015400Z` | `11.0 sec` | `3600.395` | `160.452` | `632.824` | `Contended` |

注意：

- 這兩次 run 都是在 `nvidia.com/gpu.shared: 1` 條件下完成
- API preflight 在 `pascal-continuous` 前偵測到 `2` 個既有 GPU compute process
- 因此目前最適合將它們解讀為 `shared GPU usable baseline`
- 若要做正式對外報告的 hardware baseline，仍建議在較乾淨的 isolation 條件下重跑

## 2026-07-05 Isolated Baseline

後續已在同一個 target pod 上完成一輪 isolation rerun：

- temporary scale down:
  - `intent-lab/yolo26n-focus`
  - `intent-lab/yolo26n-bg-2`
- benchmark preflight after scale-down:
  - `gpu_process_count_before = 0`
  - `gpu_contended = false`
  - `gpu_preflight_status = Idle`
- rerun 完成後，兩個 YOLO deployment 已恢復

建議正式引用的 baseline：

| Profile | Run ID | Duration | Prompt TPS (`pp`) | Generation TPS (`tg`) | Prompt + Generation TPS (`pg`) | GPU Preflight |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `pascal-smoke` | `llamacpp-pascal-smoke-run-20260705T020757Z` | `4.0 sec` | `3653.644` | `156.710` | `432.436` | `Idle` |
| `pascal-continuous` | `llamacpp-pascal-continuous-run-20260705T020802Z` | `11.0 sec` | `3610.145` | `156.691` | `619.870` | `Idle` |

## 2026-07-07 Gemma 4 E2B Q4_K_M Baseline

Gemma 模型已在 `icclz1` 的 GTX 1080 Ti target pod 上完成 llama.cpp CUDA benchmark。

驗證項目：

- model file: `/models/gemma/gemma-4-E2B-it-Q4_K_M.gguf`
- host path: `/var/lib/pre6g/models/gemma-4-e2b-it-gguf/gemma-4-E2B-it-Q4_K_M.gguf`
- file size: `3106736256 bytes`
- sha256: `9378bc471710229ef165709b62e34bfb62231420ddaf6d729e727305b5b8672d`
- image pull policy: `Never`
- container tool: `/usr/local/bin/llama-bench`

執行指令：

```bash
kubectl -n ai-serving exec deploy/llamacpp-gemma4-e2b-q4km-bench -- /usr/local/bin/llama-bench \
  -m /models/gemma/gemma-4-E2B-it-Q4_K_M.gguf \
  -ngl 999 \
  -p 512 \
  -n 128 \
  -r 3
```

實測結果：

| Model | Backend | GPU | GPU Offload | Prompt TPS (`pp512`) | Generation TPS (`tg128`) | llama.cpp build |
| --- | --- | --- | --- | ---: | ---: | --- |
| Gemma 4 E2B Q4_K_M | CUDA | NVIDIA GeForce GTX 1080 Ti | `ngl=999` | `2729.31 ± 15.72` | `103.63 ± 0.05` | `2d97363` |

補充：

- GPU compute capability: `6.1`
- VRAM: `11170 MiB`
- model size: `2.88 GiB`
- parameter count: `4.65B`

## Shared GPU Caveat

這個 target 使用：

- `nvidia.com/gpu.shared: 1`

因此每次 benchmark 都必須記錄 preflight：

```bash
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
```

若有其他 compute process，結果應標註：

- `Contended GPU — throughput may not represent an isolated baseline.`
