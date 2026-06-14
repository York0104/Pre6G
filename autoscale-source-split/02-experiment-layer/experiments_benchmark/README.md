# experiments_benchmark

這個目錄提供一套 **master-side remote benchmark orchestration**，用途是：

- 從 master 端透過 SSH 觸發 worker 本地 benchmark
- 在 benchmark 執行期間同步收集 node-level 監控資料
- 拉回 worker 端 summary / monitor artifacts
- 自動生成單次 run 與整體 suite 的圖表

這條 workflow 的定位，和 `experiments_yolo/` 類似，但 benchmark workload 不是 pod/service，而是 **worker 本地腳本**。

---

## 目錄功能

這個目錄主要負責四件事：

1. **單次 remote benchmark 執行**
2. **整套 benchmark suite 執行**
3. **單次 run 繪圖**
4. **整套 suite 繪圖**

支援的三類 benchmark：

- `cpu_bound`
- `ram_bound`
- `vram_bound`

它們對應 worker 端既有 wrapper：

- `cpu_bound` -> `/home/mirc516/Pre6g/run_task_cpu.sh`
- `ram_bound` -> `/home/mirc516/Pre6g/run_task_ram.sh`
- `vram_bound` -> `/home/mirc516/Pre6g/run_task_vram.sh`

---

## 檔案介紹

### 1. `run_remote_benchmark_with_metrics.sh`

單次 remote run 的主入口。

負責：

- task-aware preflight
- SSH 到 worker 啟動 benchmark wrapper
- 啟動 master-side 監控：
  - `vm_aggregator`
  - `kubectl top node`
  - remote `nvidia-smi`
- 拉回 worker artifacts
- 解析 summary
- 產生 `master_verdict.json`
- 呼叫單次 run plotter

這支是單任務主控腳本。

---

### 2. `run_remote_benchmark_suite.sh`

整套 benchmark suite 的主入口。

負責：

- 依序執行：
  - `cpu_bound`
  - `ram_bound`
  - `vram_bound`
- suite 開始前先抓 baseline
- 每個任務後做 fixed cooldown observation
- 輪詢 worker 資源是否已回到 baseline 附近
- 整理 `suite_manifest.csv`
- 產出 `suite_summary.json`
- 呼叫 suite plotter

這支是整體 orchestrator。

---

### 3. `plot_remote_benchmark_run.py`

單次 run 的繪圖工具。

輸入：

- `kubectl_top_node_1s.log`
- `worker_nvidia_smi_1s.csv`
- `time_window.txt`

輸出：

- `combined_monitor.csv`
- `measurement_raw.csv`
- `resource_utilization.png`
- `plots/resource_utilization.png`
- `plot_summary.json`

圖中只畫四條：

- CPU
- RAM
- GPU
- VRAM

---

### 4. `plot_remote_benchmark_suite.py`

整套 suite 的繪圖工具。

輸入：

- `suite_manifest.csv`
- 各 run 的 `combined_monitor.csv`

輸出：

- `suite_resource_utilization.png`
- `suite_plot_summary.json`

這支會把 suite 中每個 task 畫成一個 panel。

---

## 架構說明

### master 端負責

- orchestration
- metrics collection
- artifact pull
- verdict / manifest / suite summary
- plotting

### worker 端負責

- 真正執行 benchmark
- 產生 benchmark-specific summary / monitor CSV

---

## 前提條件

### 1. master 可以無密碼 SSH 到 worker

至少要通：

```bash
ssh mirc516@100.90.127.1 'echo ok'
```

### 2. worker 端已具備 benchmark wrapper

預期存在：

- `/home/mirc516/Pre6g/run_task_cpu.sh`
- `/home/mirc516/Pre6g/run_task_ram.sh`
- `/home/mirc516/Pre6g/run_task_vram.sh`

### 3. worker wrapper contract

成功判定使用兩層：

1. process exit code = `0`
2. summary JSON 內 `success == true`

master 端 orchestration 依賴這個 contract。

---

## Task-aware Preflight

目前 preflight 不是直接把 worker 端 generic `check_benchmark_env.sh` 整支照跑，而是由 master 端依 task 類型做 remote preflight。

### `cpu_bound`

檢查：

- `ffmpeg`
- `libx265`
- Python env import
- `input_4k.mp4`

### `ram_bound`

檢查：

- `redis-cli ping`
- Python env import

### `vram_bound`

檢查：

- Ollama service
- `qwen3:32b`
- `nvidia-smi`
- Python env import
- `Attention Is All You Need.pdf`

---

## 正式 baseline 理解

這套 orchestration 目前是按照 worker 正式 baseline 去理解任務。

### CPU 正式組

- `codec=libx265`
- `preset=veryslow`
- `crf=28`
- `threads=0`
- `parallel_jobs=2`
- `min_duration_seconds=3000`
- `timeout_seconds=5400`

注意：

- `min_duration_seconds=3000` 是「至少跑到這麼久」
- 真正停止還要等當前 ffmpeg round 結束

### RAM 正式組

- `target_keys=6000000`
- `data_size_kb=16`
- `batch_size=4000`
- `stop_on_memory_threshold_gb=96`
- `hold_seconds=2700`
- `cleanup=1`
- `post_cleanup_purge=1`
- `post_cleanup_restart_redis=0`

### VRAM 正式組

- `model=qwen3:32b`
- `concurrency=2`
- `repeat=28`
- `max_chars=260000`
- `num_ctx=32768`
- `num_predict=256`
- `keep_alive=0`
- `min_duration_seconds=3000`

### Suite 正式時間語意

- `warmup_seconds=300`
- `steady_seconds=2700`
- `cooldown_seconds=900`

---

## master 預設如何傳參

如果你 **沒有明確指定 duration 類參數**，master 會主動套用一組統一預設，方便 remote 任務時長與監控窗對齊：

- `DEFAULT_WARMUP_SECONDS=300`
- `DEFAULT_STEADY_SECONDS=2700`
- `DEFAULT_COOLDOWN_SECONDS=900`

對應如下：

- `cpu_bound` -> 傳 `MIN_DURATION_SECONDS = 3000`
- `ram_bound` -> 傳 `HOLD_SECONDS = 2700`
- `vram_bound` -> 傳 `MIN_DURATION_SECONDS = 3000`

如果你有明確指定：

- `MIN_DURATION_SECONDS`
- `HOLD_SECONDS`
- `DURATION`

則 master 會優先用你傳的值。

---

## 結果目錄結構

### 單次 run

輸出位置：

```text
autoscale-source-split/02-experiment-layer/experiments_benchmark/results/<RUN_ID>/
```

常見檔案：

- `experiment_config.txt`
- `deploy_before.txt`
- `deploy_after.txt`
- `pods_before.txt`
- `pods_after.txt`
- `events_before.txt`
- `events_after.txt`
- `preflight.log`
- `remote_wrapper.log`
- `measurement.log`
- `time_window.txt`
- `vm_aggregator_timeseries.csv`
- `vm_aggregator_timeseries.log`
- `vm_aggregator_training_features.csv`
- `vm_aggregator_training_features.log`
- `kubectl_top_node_1s.log`
- `kubectl_top_1s.log`
- `worker_nvidia_smi_1s.csv`
- `worker_nvidia_smi_1s.err`
- `nvidia_smi_gpu_1s.csv`
- `nvidia_smi_gpu_1s.err`
- `vm_metrics/*.json`
- `worker_logs/`
- `master_verdict.json`
- `combined_monitor.csv`
- `measurement_raw.csv`
- `resource_utilization.png`
- `plots/`
- `summary.txt`
- `plot_summary.json`

### suite

輸出位置：

```text
autoscale-source-split/02-experiment-layer/experiments_benchmark/results/<SUITE_ID>/
```

常見檔案：

- `baseline.json`
- `suite_manifest.csv`
- `suite_summary.json`
- `summary.txt`
- 各 task console log
- `suite_resource_utilization.png`
- `plots/suite_resource_utilization.png`
- `suite_plot_summary.json`

---

## 結構化輸出 contract

### per-run

`master_verdict.json` 會至少包含：

- preflight 結果
- remote wrapper exit code
- artifact pull 結果
- summary 狀態
- plotting 狀態
- start / remote_end / end 時間
- artifact 路徑

### suite

`suite_manifest.csv` 會至少包含：

- `task`
- `run_id`
- `run_dir`
- `status`
- `failure_category`
- `remote_exit_code`
- `summary_success`
- `task_start_epoch`
- `task_end_epoch`
- `remote_end_epoch`
- `cooldown_ready`
- `cooldown_extra_wait_sec`
- artifact paths

`suite_summary.json` 會至少包含：

- `suite_id`
- `task_order`
- `tasks`
- `status`
- `failure_category`
- plotting 結果

---

## 錯誤分類

目前至少會分類：

- `preflight_failed`
- `remote_wrapper_failed`
- `artifact_pull_failed`
- `summary_missing`
- `summary_parse_failed`
- `cooldown_timeout`
- `plotting_failed`

其中 `plotting_failed` 預設不是 suite 致命錯誤；會記錄在 summary，但不一定讓整體 exit code 失敗。

---

## 如何使用

### 1. 跑單次 CPU

```bash
cd /home/icclz2/Pre6G

TASK=cpu_bound \
WORKER_SSH='mirc516@100.90.127.1' \
WORKER_NODE_NAME='ICCL-S3-251230' \
MIN_DURATION_SECONDS=3000 \
TIMEOUT_SECONDS=5400 \
PARALLEL_JOBS=2 \
bash autoscale-source-split/02-experiment-layer/experiments_benchmark/run_remote_benchmark_with_metrics.sh
```

### 2. 跑單次 RAM

```bash
cd /home/icclz2/Pre6G

TASK=ram_bound \
WORKER_SSH='mirc516@100.90.127.1' \
WORKER_NODE_NAME='ICCL-S3-251230' \
HOLD_SECONDS=2700 \
STOP_ON_MEMORY_THRESHOLD_GB=96 \
TARGET_KEYS=6000000 \
DATA_SIZE_KB=16 \
BATCH_SIZE=4000 \
bash autoscale-source-split/02-experiment-layer/experiments_benchmark/run_remote_benchmark_with_metrics.sh
```

### 3. 跑單次 VRAM

```bash
cd /home/icclz2/Pre6G

TASK=vram_bound \
WORKER_SSH='mirc516@100.90.127.1' \
WORKER_NODE_NAME='ICCL-S3-251230' \
MIN_DURATION_SECONDS=3000 \
MODEL_NAME=qwen3:32b \
CONCURRENCY=2 \
REPEAT=28 \
MAX_CHARS=260000 \
NUM_CTX=32768 \
NUM_PREDICT=256 \
KEEP_ALIVE=0 \
bash autoscale-source-split/02-experiment-layer/experiments_benchmark/run_remote_benchmark_with_metrics.sh
```

### 4. 跑整套 suite

```bash
cd /home/icclz2/Pre6G

bash autoscale-source-split/02-experiment-layer/experiments_benchmark/run_remote_benchmark_suite.sh
```

### 5. 指定 cooldown policy

```bash
COOLDOWN_TIMEOUT_POLICY=warn-and-continue \
bash autoscale-source-split/02-experiment-layer/experiments_benchmark/run_remote_benchmark_suite.sh
```

或：

```bash
COOLDOWN_TIMEOUT_POLICY=fail \
bash autoscale-source-split/02-experiment-layer/experiments_benchmark/run_remote_benchmark_suite.sh
```

---

## smoke test 建議

正式 baseline 很重，尤其 CPU。

如果你只是驗證 orchestration 鏈路，建議先用較短參數，例如：

```bash
cd /home/icclz2/Pre6G

MIN_DURATION_SECONDS=60 \
HOLD_SECONDS=60 \
FIXED_COOLDOWN_SECONDS=30 \
COOLDOWN_TIMEOUT_SECONDS=120 \
COOLDOWN_TIMEOUT_POLICY=warn-and-continue \
bash autoscale-source-split/02-experiment-layer/experiments_benchmark/run_remote_benchmark_suite.sh
```

注意：

- 這對 `cpu_bound` 不一定是快速完成，因為 `libx265 + veryslow + parallel_jobs=2` 單輪轉碼本身就可能很久
- 如果只是 smoke test，建議另外準備較輕的 smoke profile

---

## 繪圖方式

### 單次 run

單次 run 完成後會自動嘗試產出：

- `combined_monitor.csv`
- `measurement_raw.csv`
- `resource_utilization.png`
- `plots/resource_utilization.png`

手動重畫：

```bash
python3 autoscale-source-split/02-experiment-layer/experiments_benchmark/plot_remote_benchmark_run.py \
  --run-dir autoscale-source-split/02-experiment-layer/experiments_benchmark/results/<RUN_ID>
```

### suite

手動重畫：

```bash
python3 autoscale-source-split/02-experiment-layer/experiments_benchmark/plot_remote_benchmark_suite.py \
  --suite-dir autoscale-source-split/02-experiment-layer/experiments_benchmark/results/<SUITE_ID>
```

---

## 目前已知限制

1. 這套 workflow 主要抓 **node-level metrics**
   - `kubectl top node`
   - `vm_aggregator`
   - remote `nvidia-smi`

2. benchmark-specific 細節仍以 worker wrapper 輸出的 monitor CSV 為主
   - CPU：`video_cpu.csv`
   - RAM：`redis_stats.csv`
   - VRAM：`qwen_gpu.csv`

3. CPU 任務的 `min_duration_seconds` 不是硬中斷時間
   - 會等當前 ffmpeg round 結束

---

## 建議使用方式

- **正式實驗**：直接用 worker baseline 正式參數
- **鏈路驗證**：另外用較輕的 smoke profile
- **分析與畫圖**：直接讀這個目錄下產生的 run / suite artifacts
