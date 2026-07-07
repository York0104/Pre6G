# GTX 1080 Ti llama.cpp Offline Benchmark

這份文件記錄目前 `GTX 1080 Ti / Pascal CC 6.1` 在 `Pre6G` 內的正式 benchmark 方向。

## Why llama.cpp Instead of vLLM

`GTX 1080 Ti` 已不再作為 `vLLM` 正式支援 target：

- Pascal / `CC 6.1`
- `vLLM` 官方支援下限高於這個世代
- 先前 `vllm bench throughput` 已在 `1080 Ti` 上遇到 CUDA 相容性問題

因此目前正式方向改為：

- runtime: `llama.cpp`
- benchmark mode: `offline`
- tool: `llama-bench`

## Runtime Identity

- runtime: `llamacpp`
- benchmark_mode: `offline`
- gpu_arch: `sm61`
- gpu_model: `NVIDIA GeForce GTX 1080 Ti`

## Fixed Profiles

- `pascal-smoke`
- `pascal-continuous`

這些 profile 是固定 allowlist，不接受任意 CLI 參數。

其中：

- `Prompt TPS` 對應 `pp`
- `Generation TPS` 對應 `tg`
- `Prompt + Generation TPS` 對應 `pg`

因此 benchmark command 需要顯式包含 `-pg <n_prompt>,<n_gen>`，不能只靠 `--n-prompt` 與 `--n-gen` 推導。

## 2026-07-05 Live Validation

本輪已完成實機驗證：

- image build: `pre6g/llamacpp-cuda118-sm61:gemma4-e2b-q4km`
- image import target: `icclz1`
- target pod: `deploy/llamacpp-gemma4-e2b-q4km-bench`
- API control path:
  `autoscale_api -> kubectl exec -> llama-bench -> JSON parser -> history/dashboard`

### `pascal-smoke`

- run id: `llamacpp-pascal-smoke-run-20260705T014938Z`
- status: `succeeded`
- duration: `5.0 sec`
- Prompt TPS (`pp`): `3356.873 tok/s`
- Generation TPS (`tg`): `161.313 tok/s`
- Prompt + Generation TPS (`pg`): `443.227 tok/s`

### `pascal-continuous`

- run id: `llamacpp-pascal-continuous-run-20260705T015400Z`
- status: `succeeded`
- duration: `11.0 sec`
- Prompt TPS (`pp`): `3600.395 tok/s`
- Generation TPS (`tg`): `160.452 tok/s`
- Prompt + Generation TPS (`pg`): `632.824 tok/s`

### Interpretation Boundary

這兩次 run 都不是 isolated single-tenant GPU：

- node: `icclz1`
- GPU resource: `nvidia.com/gpu.shared: 1`
- API preflight: `gpu_contended = true`
- sampled background GPU processes before `pascal-continuous`: `2`

因此目前最嚴謹的解讀是：

- `pascal-smoke` 與 `pascal-continuous` 已證明這條 `llama.cpp` offline benchmark path 可在 live cluster 正常執行
- 這些數值可作為 `shared GPU` 條件下的可用 baseline
- 這些數值不應直接宣稱為 `GTX 1080 Ti` 的 isolated peak hardware baseline

後續若要產出正式 baseline，建議先排空 `icclz1` 上其他 compute process，再重跑同一組 fixed profiles。

## 2026-07-05 Isolated Baseline

後續已實際完成一輪較乾淨的 isolation rerun：

- temporary scale down:
  - `intent-lab/yolo26n-focus`
  - `intent-lab/yolo26n-bg-2`
- benchmark preflight after scale-down:
  - `gpu_process_count_before = 0`
  - `gpu_contended = false`
  - `gpu_preflight_status = Idle`
- benchmark 完成後，兩個 YOLO deployment 已恢復到 `readyReplicas = 1`

### Isolated `pascal-smoke`

- run id: `llamacpp-pascal-smoke-run-20260705T020757Z`
- status: `succeeded`
- duration: `4.0 sec`
- Prompt TPS (`pp`): `3653.644 tok/s`
- Generation TPS (`tg`): `156.710 tok/s`
- Prompt + Generation TPS (`pg`): `432.436 tok/s`

### Isolated `pascal-continuous`

- run id: `llamacpp-pascal-continuous-run-20260705T020802Z`
- status: `succeeded`
- duration: `11.0 sec`
- Prompt TPS (`pp`): `3610.145 tok/s`
- Generation TPS (`tg`): `156.691 tok/s`
- Prompt + Generation TPS (`pg`): `619.870 tok/s`

### Recommended Baseline Interpretation

目前最適合作為正式 `GTX 1080 Ti / llama.cpp / Gemma 4 E2B Q4_K_M` baseline 的，是這組 isolated rerun，而不是前一組 shared-GPU 結果。

建議後續引用時優先使用：

- `pascal-smoke`
  - `pp = 3653.644 tok/s`
  - `tg = 156.710 tok/s`
  - `pg = 432.436 tok/s`
- `pascal-continuous`
  - `pp = 3610.145 tok/s`
  - `tg = 156.691 tok/s`
  - `pg = 619.870 tok/s`

## Dashboard Semantics

- `Prompt TPS` = `pp` mean tokens/s
- `Generation TPS` = `tg` mean tokens/s
- `Prompt + Generation TPS` = `pg` mean tokens/s
- `Waiting Requests` = `N/A — offline benchmark`
- `KV Cache Usage` = `N/A — offline benchmark`
- `Result Freshness` = `now - completed_at`

## GPU Contention

由於 target 使用 shared GPU resource，benchmark 前會先記錄：

```bash
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
```

若有其他 compute process，UI 會標記：

- `Contended GPU — throughput may not represent an isolated baseline.`

## Image Distribution Reality

目前 `icclz2` 已可成功 build 本地 image：

- `pre6g/llamacpp-cuda118-sm61:gemma4-e2b-q4km`

但 live deployment 仍取決於 image 如何送達 `icclz1`：

- 若 Harbor 可用，可改走 registry path
- 若 Harbor 暫時不可用，可使用
  `k3s-migration-bundle-sanitized/llm-serving/llamacpp-qwen-1080ti/build_and_import_to_icclz1.sh`
  透過互動式 `ssh` 串流匯入 `sudo k3s ctr images import -`

另外，在沒有 NVIDIA runtime 的一般 `docker run` 下，`llama-bench` 會缺少 `libcuda.so.1`；
正式 target pod 需依賴 `runtimeClassName: nvidia` 注入 driver libraries，這是預期行為。
