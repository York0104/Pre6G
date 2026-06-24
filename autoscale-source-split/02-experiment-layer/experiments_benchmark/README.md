# experiments_benchmark

這個目錄整理了目前 Pre6G 的四瓶頸 benchmark 控制與繪圖流程，目標是用一致的方式觀察：

- CPU-bound
- RAM-bound
- VRAM-bound
- GPU-bound

其中前 3 類沿用 **master -> worker 本地腳本** 的 remote orchestration；第 4 類 GPU-bound 則改成 **master -> k3s pod on GPU node** 的 experiment mode，但結果輸出仍對齊到這個目錄的 benchmark 結構。

---

## 實驗設計

### 四個 bound 的定位

1. `CPU-bound`
   - 任務：`video_compression.py`
   - 執行位置：worker 本地
   - 核心壓力：`ffmpeg + libx265 + veryslow`
   - 目標：讓 CPU 長時間接近滿載，GPU / VRAM 干擾低

2. `RAM-bound`
   - 任務：`redis_test.py`
   - 執行位置：worker 本地
   - 核心壓力：Redis 寫入大量 key 並 hold
   - 目標：讓主機 RAM 使用率長時間維持高檔

3. `VRAM-bound`
   - 任務：`long_text_llm.py`
   - 執行位置：worker 本地
   - 核心壓力：`qwen3:32b` 長上下文推論
   - 目標：長時間佔用顯卡記憶體，並觀察 GPU / VRAM 行為

4. `GPU-bound`
   - 任務：YOLO experiment mode
   - 執行位置：k3s pod，指定到 4090 節點
   - 核心壓力：容器內連續 batch infer，不走高併發 HTTP 壓測
   - 目標：盡量讓單卡 GPU utilization 長時間處於高載，且避免主因變成 VRAM / CPU / RAM

### 階段概念

所有圖表都盡量對齊這三段：

- `warm-up`
- `steady-state`
- `cooldown`

worker-local 三類任務由 master 根據時間窗與任務型態推導 phase；GPU experiment mode 會直接產生 `phase_windows.csv`，因此 phase 對齊更直接。

### 為什麼不是只靠固定 sleep

suite 切換任務時，除了固定 cooldown 觀察，還會再比對 baseline 附近的資源狀態，避免前一個任務殘留資源壓力直接污染下一個任務。

---

## 目錄功能

這個目錄目前負責 5 件事：

1. 單次 remote benchmark 執行
2. 三個 worker-local benchmark 的 suite orchestration
3. 單次 run 繪圖
4. suite-level 繪圖
5. 四個 bound 的整體對照圖

---

## 主要程式

### 1. `run_remote_benchmark_with_metrics.sh`

單次 remote run 主入口，支援：

- `cpu_bound`
- `ram_bound`
- `vram_bound`

主要功能：

- task-aware preflight
- SSH 到 worker 啟動對應 wrapper
- 在 master 側同步收集監控
- 拉回 worker summary / monitor artifacts
- 產生 `master_verdict.json`
- 呼叫單次 run plotter

對應 worker wrapper：

- `cpu_bound` -> `/home/mirc516/Pre6g/run_task_cpu.sh`
- `ram_bound` -> `/home/mirc516/Pre6g/run_task_ram.sh`
- `vram_bound` -> `/home/mirc516/Pre6g/run_task_vram.sh`

### 2. `run_remote_benchmark_suite.sh`

三個 worker-local 任務的 suite orchestrator。

主要功能：

- 依序執行 `cpu_bound -> ram_bound -> vram_bound`
- suite 開始前抓 baseline
- 每個任務完成後先做固定 cooldown
- 再輪詢 worker 狀態，等資源接近 baseline
- 產出 `suite_manifest.csv`
- 產出 `suite_summary.json`
- 呼叫 suite plotter

### 3. `plot_remote_benchmark_run.py`

單次 run 繪圖器。

主要輸入：

- `kubectl_top_node_1s.log`
- `worker_nvidia_smi_1s.csv`
- `time_window.txt`
- `phase_windows.csv`（若有）

主要輸出：

- `combined_monitor.csv`
- `measurement_raw.csv`
- `resource_utilization.png`
- `plots/resource_utilization.png`
- `plot_summary.json`

### 4. `plot_remote_benchmark_suite.py`

suite-level 繪圖器。

主要輸入：

- `suite_manifest.csv`
- 各 task run 目錄下的 `combined_monitor.csv`

主要輸出：

- `suite_resource_utilization.png`
- `suite_plot_summary.json`

### 5. `plot_four_bounds_overview.py`

四個 bound 的整體對照圖工具。

主要功能：

- 把 CPU / RAM / VRAM / GPU 四個 run 畫成同一張多 panel 圖
- 每個 panel 固定畫 4 條線：
  - CPU
  - RAM
  - GPU
  - VRAM
- 可選 rolling median 平滑

目前輸出檔名：

- `four_bounds_resource_utilization.png`
- `four_bounds_resource_utilization_smoothed.png`

### 6. `../experiments_yolo/single_pod_gpu_bound/run_single_pod_gpu_experiment_mode_on_node.sh`

GPU-bound 的正式入口，雖然檔案不在本目錄，但現在會把結果寫回 `experiments_benchmark/results/`，因此已視為這套 benchmark 的一部分。

主要功能：

- 在指定 GPU node 建立單 pod
- 用 ConfigMap 掛載 `gpu_burn.py`
- 在 pod 內做連續 batch infer
- 在 master 側收：
  - `vm_aggregator`
  - `kubectl top node`
  - remote `nvidia-smi`
- 產生 benchmark-compatible artifacts：
  - `combined_monitor.csv`
  - `resource_utilization.png`
  - `phase_windows.csv`
  - `benchmark_compat_summary.json`

### 7. `../yolo26_workload/gpu_burn.py`

GPU-bound experiment mode 的容器內 workload。

主要功能：

- 根據 env var 控制 model / imgsz / batch / repeat / duration
- 先 warmup，再進入持續 infer
- 週期性輸出 JSON progress
- 任務結束輸出 summary JSON

---

## preflight 設計

`run_remote_benchmark_with_metrics.sh` 現在是 task-aware preflight，不會對所有任務一律檢查完整 GPU / Ollama / PDF。

### `cpu_bound`

- `ffmpeg` 存在
- `libx265` encoder 可用
- Python env 可用
- `input_4k.mp4` 存在

### `ram_bound`

- `redis-server` / `redis-cli ping`
- Python env 可用

### `vram_bound`

- Ollama service 可達
- `http://127.0.0.1:11434/api/tags` 中可找到 `qwen3:32b`
- `nvidia-smi` 可用
- Python env 可用
- `Attention Is All You Need.pdf` 存在

---

## 正式 baseline

### CPU-bound 正式組

- `codec=libx265`
- `preset=veryslow`
- `crf=28`
- `threads=0`
- `parallel_jobs=2`
- `min_duration_seconds=3000`
- `timeout_seconds=5400`

注意：`min_duration_seconds` 是至少執行多久，不是硬切斷。若當前 ffmpeg round 尚未完成，任務會等該輪結束。

### RAM-bound 正式組

- `target_keys=6000000`
- `data_size_kb=16`
- `batch_size=4000`
- `stop_on_memory_threshold_gb=96`
- `hold_seconds=2700`
- `cleanup=1`
- `post_cleanup_purge=1`
- `post_cleanup_restart_redis=0`

### VRAM-bound 正式組

- `model=qwen3:32b`
- `repeat=28`
- `concurrency=2`
- `max_chars=260000`
- `num_ctx=32768`
- `num_predict=256`
- `keep_alive=0`
- `min_duration_seconds=3000`

### Suite 正式時間

- `DEFAULT_WARMUP_SECONDS=300`
- `DEFAULT_STEADY_SECONDS=2700`
- `DEFAULT_COOLDOWN_SECONDS=900`

也就是 5 分鐘 warm-up、45 分鐘 steady-state、15 分鐘 cooldown。

---

## 使用方式

### 1. 跑單次 CPU-bound

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark

TASK=cpu_bound \
RUN_ID=cpu_bound_$(date +%Y%m%d_%H%M%S) \
bash run_remote_benchmark_with_metrics.sh
```

### 2. 跑單次 RAM-bound

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark

TASK=ram_bound \
RUN_ID=ram_bound_$(date +%Y%m%d_%H%M%S) \
bash run_remote_benchmark_with_metrics.sh
```

### 3. 跑單次 VRAM-bound

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark

TASK=vram_bound \
RUN_ID=vram_bound_$(date +%Y%m%d_%H%M%S) \
bash run_remote_benchmark_with_metrics.sh
```

### 4. 跑三任務 suite

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark

bash run_remote_benchmark_suite.sh
```

若只想做短版 smoke test，可覆蓋：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark

MIN_DURATION_SECONDS=60 \
HOLD_SECONDS=60 \
PARALLEL_JOBS=1 \
PRESET=medium \
FIXED_COOLDOWN_SECONDS=30 \
COOLDOWN_TIMEOUT_SECONDS=120 \
COOLDOWN_TIMEOUT_POLICY=warn-and-continue \
bash run_remote_benchmark_suite.sh
```

### 5. 跑 GPU-bound experiment mode

這支會把結果直接寫進 `experiments_benchmark/results/`。

```bash
RESULT_ROOT='/home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results' \
GPU_NODE_NAME=iccl-s3-251230 \
NODE_SSH='mirc516@100.90.127.1' \
IMAGE_REF='local/yolo26n:0.2' \
IMAGE_PULL_POLICY=Never \
YOLO_MODEL='yolo26m.pt' \
YOLO_IMGSZ=1536 \
BATCH_SIZE=24 \
REPEAT=1 \
DURATION=300 \
START_DELAY_SECONDS=10 \
WARMUP_ITERS=2 \
CPU_REQUEST=4000m \
CPU_LIMIT=8000m \
MEMORY_REQUEST=8Gi \
MEMORY_LIMIT=16Gi \
CLEANUP_ON_EXIT=1 \
bash /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_gpu_bound/run_single_pod_gpu_experiment_mode_on_node.sh
```

### 6. 重畫單次 run

```bash
/home/icclz2/Pre6G/iccl/bin/python \
plot_remote_benchmark_run.py \
  --run-dir /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/cpu_bound_20260614_223757
```

### 7. 重畫 suite-level 圖

```bash
/home/icclz2/Pre6G/iccl/bin/python \
plot_remote_benchmark_suite.py \
  --suite-dir /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/remote_suite_20260614_223756
```

### 8. 畫四個 bound 的總覽圖

```bash
/home/icclz2/Pre6G/iccl/bin/python \
plot_four_bounds_overview.py \
  --cpu-run-dir /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/cpu_bound_20260614_223757 \
  --ram-run-dir /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/ram_bound_20260614_235851 \
  --vram-run-dir /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/vram_bound_20260615_012538 \
  --gpu-run-dir /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/single_gpu_exp_iccl-s3-251230_yolo26m_pt_img1536_b24_r1_300s_20260615_131446 \
  --output /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/four_bounds_resource_utilization.png \
  --summary-output /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/four_bounds_resource_utilization.summary.json
```

平滑版：

```bash
/home/icclz2/Pre6G/iccl/bin/python \
plot_four_bounds_overview.py \
  --cpu-run-dir /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/cpu_bound_20260614_223757 \
  --ram-run-dir /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/ram_bound_20260614_235851 \
  --vram-run-dir /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/vram_bound_20260615_012538 \
  --gpu-run-dir /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/single_gpu_exp_iccl-s3-251230_yolo26m_pt_img1536_b24_r1_300s_20260615_131446 \
  --output /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/four_bounds_resource_utilization_smoothed.png \
  --summary-output /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/four_bounds_resource_utilization_smoothed.summary.json \
  --smooth-window 5
```

---

## 參數覆蓋原則

### worker-local benchmark

master 會盡量與 worker wrapper 對齊，主要靠 env var 透傳。

常用參數：

- CPU:
  - `MIN_DURATION_SECONDS`
  - `TIMEOUT_SECONDS`
  - `PARALLEL_JOBS`
  - `PRESET`
- RAM:
  - `HOLD_SECONDS`
  - `STOP_ON_MEMORY_THRESHOLD_GB`
  - `TARGET_KEYS`
  - `DATA_SIZE_KB`
- VRAM:
  - `MIN_DURATION_SECONDS`
  - `CONCURRENCY`
  - `NUM_CTX`
  - `MAX_CHARS`
  - `NUM_PREDICT`
  - `REPEAT`

若 master 沒顯式傳值，就盡量讓 worker 端使用自己的原始預設。

### GPU experiment mode

常用參數：

- `YOLO_MODEL`
- `YOLO_IMGSZ`
- `BATCH_SIZE`
- `REPEAT`
- `DURATION`
- `START_DELAY_SECONDS`
- `WARMUP_ITERS`
- `CPU_REQUEST`
- `CPU_LIMIT`
- `MEMORY_REQUEST`
- `MEMORY_LIMIT`

---

## 輸出結果結構

### 單次 worker-local run

每次 run 會落在：

```text
results/<RUN_ID>/
```

常見檔案：

- `master_verdict.json`
- `experiment_config.txt`
- `time_window.txt`
- `worker_summary.json` 或 pulled summary
- `worker_monitor.csv`
- `kubectl_top_node_1s.log`
- `worker_nvidia_smi_1s.csv`
- `combined_monitor.csv`
- `measurement_raw.csv`
- `resource_utilization.png`
- `plot_summary.json`
- `summary.txt`

### suite run

每次 suite 會落在：

```text
results/<SUITE_ID>/
```

常見檔案：

- `suite_manifest.csv`
- `suite_summary.json`
- `suite_resource_utilization.png`
- `suite_plot_summary.json`
- `summary.txt`

### GPU experiment mode run

結果同樣放在 `results/<RUN_ID>/`，但會額外有：

- `phase_windows.csv`
- `gpu_burn_summary.json`
- `benchmark_compat_summary.json`
- `vm_metrics/`

---

## 目前結果

目前這個目錄下已經有一組正式四圖整合結果：

- `results/cpu_bound_20260614_223757`
- `results/ram_bound_20260614_235851`
- `results/vram_bound_20260615_012538`
- `results/single_gpu_exp_iccl-s3-251230_yolo26m_pt_img1536_b24_r1_300s_20260615_131446`

以及四個 bound 的總覽圖：

- `results/four_bounds_resource_utilization.png`
- `results/four_bounds_resource_utilization_smoothed.png`

GPU experiment mode 這組的 benchmark-compatible summary 位於：

- [benchmark_compat_summary.json](/home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/experiments_benchmark/results/single_gpu_exp_iccl-s3-251230_yolo26m_pt_img1536_b24_r1_300s_20260615_131446/benchmark_compat_summary.json)

這組至少可確認：

- pod 成功完成
- benchmark-compatible plot 已生成
- `combined_monitor.csv` 已生成
- `phase_windows.csv` 已生成
- 可直接納入四個 bound 對照圖

---

## 圖的判讀

### 為什麼 GPU 曲線看起來像快速震盪

GPU-bound 的 YOLO experiment mode 是容器內一輪一輪 batch infer；`nvidia-smi` 又是 1 秒取樣，所以圖上常會看到高頻鋸齒，而不是像 CPU 那樣平滑貼頂。

這通常不是失敗，而是：

- 單次 infer iteration 很短
- kernel launch / synchronize / 後處理之間存在空隙
- 1 秒粒度採樣把 burst 行為放大

如果只是想做展示，可以使用平滑版：

- `four_bounds_resource_utilization_smoothed.png`

但分析時仍建議保留原始版一起看。

---

## 成功判定

### worker-local 三任務

正式成功條件：

1. remote wrapper exit code = `0`
2. worker summary JSON 中 `success == true`

### GPU experiment mode

正式成功條件：

1. pod 成功完成
2. `gpu_burn_summary.json` 存在
3. benchmark-compatible plotting 成功
4. `benchmark_compat_summary.json` 中 `success == true`

---

## 已知限制

1. CPU-bound 若使用正式參數，單輪 `ffmpeg` 很可能遠超 60 秒，smoke test 需要降 `preset` 或 `parallel_jobs`。
2. GPU-bound 若要追求更穩定的高利用率，`batch size`、`imgsz`、模型大小與資料前後處理都會影響曲線形狀。
3. suite orchestrator 目前只直接串 `cpu_bound / ram_bound / vram_bound`；GPU-bound 仍是獨立跑完後再納入四圖整合。
4. 平滑圖是展示用，不應拿來取代原始監控資料。
