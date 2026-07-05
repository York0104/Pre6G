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

- model family: `Qwen2.5-1.5B-Instruct`
- format: `GGUF`
- quantization: `Q4_K_M`
- suggested source: `bartowski/Qwen2.5-1.5B-Instruct-GGUF`
- fixed filename: `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`
- fixed in-container path: `/models/qwen/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`
- sha256: `2157775c19b6a2ecfec3233e923c7979a43855d4bde88722576c308fccca20a5`

正式跑 benchmark 前，請先把實際檔案 SHA-256 填進：

- manifest / runtime env
- autoscale_api env
- benchmark result metadata

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
  -t pre6g/llamacpp-cuda118-sm61:qwen25-15b-q4km \
  .
```

目前這顆 image 已在 `icclz2` 成功 build 成：

- image: `pre6g/llamacpp-cuda118-sm61:qwen25-15b-q4km`
- image id: `sha256:8f12722aa010...`

注意：

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
kubectl -n ai-serving get pod -l app=llamacpp-qwen25-15b-q4km-bench -o wide
```

## Smoke Validation

```bash
kubectl -n ai-serving exec deploy/llamacpp-qwen25-15b-q4km-bench -- nvidia-smi
kubectl -n ai-serving exec deploy/llamacpp-qwen25-15b-q4km-bench -- llama-bench --list-devices
kubectl -n ai-serving exec deploy/llamacpp-qwen25-15b-q4km-bench -- /bin/bash -lc '\
  llama-bench \
    --model /models/qwen/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf \
    --n-prompt 128 \
    --n-gen 64 \
    -pg 128,64 \
    --n-depth 0 \
    --batch-size 256 \
    --ubatch-size 128 \
    --n-gpu-layers -1 \
    --flash-attn off \
    --repetitions 3 \
    --output json'
```

## Metrics Semantics

- `Prompt TPS` = llama-bench `pp` mean tokens/s
- `Generation TPS` = llama-bench `tg` mean tokens/s
- `Prompt + Generation TPS` = llama-bench `pg` mean tokens/s
- `Waiting Requests` = `N/A — offline benchmark`
- `KV Cache Usage` = `N/A — offline benchmark`
- `Result Freshness` = benchmark completion age

## 2026-07-05 Measured Baseline

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
| `pascal-throughput` | `llamacpp-pascal-throughput-run-20260705T015400Z` | `11.0 sec` | `3600.395` | `160.452` | `632.824` | `Contended` |

注意：

- 這兩次 run 都是在 `nvidia.com/gpu.shared: 1` 條件下完成
- API preflight 在 `pascal-throughput` 前偵測到 `2` 個既有 GPU compute process
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
| `pascal-throughput` | `llamacpp-pascal-throughput-run-20260705T020802Z` | `11.0 sec` | `3610.145` | `156.691` | `619.870` | `Idle` |

## Shared GPU Caveat

這個 target 使用：

- `nvidia.com/gpu.shared: 1`

因此每次 benchmark 都必須記錄 preflight：

```bash
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
```

若有其他 compute process，結果應標註：

- `Contended GPU — throughput may not represent an isolated baseline.`
