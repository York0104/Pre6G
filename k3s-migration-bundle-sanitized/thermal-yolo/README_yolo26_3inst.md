# YOLO26 3-Instance Thermal Experiment README

本文件說明 `scripts/run_B_thermal_yolo26_3inst.sh` 與
`scripts/run_C_thermal_yolo26_3inst_cycles.sh` 的用途、依賴、實驗設計、
輸出資料與操作指令。這組腳本用來在單一 GPU worker 上部署三個 YOLO26n
推論服務，並在可控熱壓力循環中收集 latency、GPU telemetry、Kubernetes
狀態與 VictoriaMetrics/Netdata 聚合指標。

## 目標

這個實驗的核心問題是：

- GPU 溫度升高時，YOLO 推論 latency 是否惡化。
- 惡化發生在 server-side inference、client end-to-end、還是服務可達性層。
- GPU shared 模式下，focus workload 與 background workload 是否互相影響。
- 熱壓力、GPU clocks、power、Kubernetes pod 狀態、node/system metrics 是否能共同解釋 QoS anomaly。

## 依賴

Master node 需要：

- `bash`
- `python` / `python3`
- Python packages: `pandas`, `matplotlib`
- `kubectl`，且目前 context 可操作 cluster
- `curl`
- `ssh` 可連到 worker
- `tmux` 建議用於長跑
- repo 路徑：`~/AutoScale`
- Python venv：`~/AutoScale/iccl`

Worker node 需要：

- worker host 預設 `icclz1`
- worker IP 預設 `100.105.48.97`
- worker repo 預設 `/home/icclz1/gpu-tempctl-lab`
- `nvidia-smi`
- 熱控腳本可由 master 透過 ssh 啟動
- YOLO pod 使用的 image：`local/yolo26n:0.1`

Kubernetes / monitoring 需要：

- namespace: `intent-lab`
- YOLO deployments:
  - `yolo26n-focus`
  - `yolo26n-bg-1`
  - `yolo26n-bg-2`
- hostPorts:
  - focus: `18081`
  - bg-1: `18082`
  - bg-2: `18083`
- VictoriaMetrics service:
  - namespace `monitoring`
  - service `vm-victoria-metrics-single-server`
  - port `8428`
- Netdata service:
  - namespace `netdata`
  - service `netdata`
  - port `19999`

## 程式結構

主要腳本：

- `scripts/run_B_thermal_yolo26_3inst.sh`
  - 執行單次 thermal YOLO 3-instance experiment。
  - 建立 run directory。
  - 支援 `OUTPUT_ROOT` / `EXP_RUNS_DIR` 指定輸出根目錄。
  - scale / rollout 三個 YOLO deployment。
  - 啟動三個 latency client。
  - 啟動 GPU telemetry collector。
  - 啟動 health monitor。
  - 啟動 VM aggregator collector。
  - 若 `WORKER_NODE=icclz1` 且未手動指定 node exporter，會預設使用 `100.105.48.97:9100`。
  - Ctrl-C / TERM 時會清理背景 latency client、health monitor、GPU telemetry、VM/Netdata port-forward、thermal command。
  - 延遲啟動 thermal command。
  - 實驗結束後執行 outage labeling。
  - 若開啟 VM aggregator，自動 merge VM aggregator metrics 到 labeled dataset。

- `scripts/run_C_thermal_yolo26_3inst_cycles.sh`
  - 重複執行多個 `run_B` cycle。
  - 每個 cycle 產生獨立 run directory。
  - 支援 `OUTPUT_ROOT` / `EXP_RUNS_DIR` 指定輸出根目錄。
  - 支援 `RUN_ID_PREFIX` 指定每個 cycle 的資料夾名稱前綴。
  - Ctrl-C / TERM 時會停止目前正在執行的 cycle。
  - 每個 cycle 後 build dataset、merge VM aggregator、產圖。
  - 適合長跑，例如 12 cycles 或 24 cycles。

相關分析程式：

- `experiments/thermal_analysis/yolo26_latency_client_stable.py`
  - 對 `/infer` 發送固定 image request。
  - 輸出 client latency、server latency、HTTP 狀態、錯誤訊息。

- `experiments/thermal_analysis/detect_service_outage.py`
  - 讀取三個 raw latency CSV。
  - 偵測 service outage / unreachable / degraded windows。
  - 輸出 outage-labeled latency rows。

- `experiments/thermal_analysis/build_thermal_yolo_dataset.py`
  - 讀取 outage-labeled latency、run metadata、GPU SMI telemetry。
  - 依 phase schedule 加上 thermal labels。
  - 產生 `thermal_yolo_labeled_dataset.csv`。

- `experiments/thermal_analysis/collect_vm_aggregator_csv.py`
  - 週期性呼叫 `vm_aggregator.py`。
  - 將 JSON flatten 成 `vmagg.*` 欄位。
  - 輸出 `metrics/vm_aggregator_<node>.csv`。
  - aggregator process 失敗時會保留較完整 stderr，最多約 4000 字，包含 traceback 前後段。

- `experiments/thermal_analysis/merge_vmagg_into_thermal_dataset.py`
  - 用 nearest timestamp asof merge。
  - 將 VM aggregator CSV 合併進 labeled dataset。
  - 輸出 `thermal_yolo_labeled_dataset_with_vmagg.csv`。

- `experiments/thermal_analysis/plot_thermal_yolo_dataset.py`
  - 根據 labeled dataset 產生基礎圖與 summary。

Deployment：

- `experiments/yolo26_k8s/yolo26_3inst_icclz1.yaml`
  - 三個 YOLO deployment 固定在 `icclz1`。
  - 使用 `nvidia.com/gpu.shared: "1"`。
  - 三個服務共用 GPU，透過不同 hostPort 暴露。

## 實驗設計

單次 `run_B` 的 phase schedule：

| Phase | 預設秒數 | Label | 意義 |
| --- | ---: | --- | --- |
| `pre_normal` | 120 | `normal` | 熱壓力前 baseline |
| `ramp_up` | 60 | `transition` | 開始加熱，系統進入變動狀態 |
| `high_temp_hold` | 300 | `thermal_anomaly` | 維持高溫，觀察 QoS 退化 |
| `ramp_down` | 60 | `transition` | 解除熱壓力，系統冷卻中 |
| `post_normal` | 120 | `recovery` | 觀察恢復後表現 |

長跑 `run_C` 會重複上述 cycle。每個 cycle 是獨立 run directory，所以後續可以分 cycle 分析，也可以用 `merge_thermal_yolo_cycles.py` 合併多個 cycle。

三個服務角色：

- focus instance:
  - port `18081`
  - request interval 通常較密，例如 `0.2s`
  - 代表主要服務品質觀察對象

- background instances:
  - ports `18082`, `18083`
  - request interval 通常較疏，例如 `0.3s`
  - 製造同 GPU 上的競爭負載

Latency 定義：

- `latency_ms_client`
  - client 端 end-to-end latency。
  - 包含網路、排隊、HTTP、server 處理與 response 回傳。

- `server_latency_ms`
  - YOLO app 內部回報的 inference time。
  - 主要量測 `model.predict()` 區段。

## 實驗理由

只看單一 YOLO instance 時，GPU 熱壓力造成的 latency 變化可能不明顯，也難以區分
server compute 問題與 client/network/queueing 問題。三個 instance 共用 GPU 可以更接近
多租戶或多服務部署狀態，讓以下現象更容易被觀察：

- GPU shared 模式下的資源競爭。
- thermal throttling 對 SM clock、power、latency 的影響。
- focus workload 在 background workload 存在時的 QoS 變化。
- service outage 與 pure latency degradation 的差異。
- node/pod/system metrics 與 application-level latency 的對齊關係。

## 實驗意義

這組資料可用於：

- 建立 thermal performance model。
- 建立 QoS anomaly detector。
- 比較 `server_latency_ms` 與 `latency_ms_client` 的退化來源。
- 分析 GPU shared deployment 是否放大 tail latency。
- 評估 multi-node monitor / VM aggregator metrics 對 anomaly explanation 的價值。
- 產生可重複的長時間 thermal stress dataset。

## 輸出目錄

每次 run 預設會輸出到：

```text
~/exp_runs/<RUN_ID>/
```

可用 `OUTPUT_ROOT` 或 `EXP_RUNS_DIR` 指定輸出根目錄：

```bash
OUTPUT_ROOT="$HOME/exp_runs/my_thermal_90C_run" bash scripts/run_C_thermal_yolo26_3inst_cycles.sh
```

`run_C` 會在 `OUTPUT_ROOT` 下建立每個 cycle 的資料夾。可用 `RUN_ID_PREFIX`
指定 cycle 資料夾前綴：

```text
<OUTPUT_ROOT>/<RUN_ID_PREFIX>_cycle1_YYYYMMDD_HHMMSS/
<OUTPUT_ROOT>/<RUN_ID_PREFIX>_cycle2_YYYYMMDD_HHMMSS/
```

典型結構：

```text
~/exp_runs/<RUN_ID>/
├── run_metadata.json
├── raw_latency/
│   ├── focus_inst1_raw.csv
│   ├── bg_inst2_raw.csv
│   └── bg_inst3_raw.csv
├── metrics/
│   ├── gpu_smi_icclz1.csv
│   ├── healthz_ports.csv
│   └── vm_aggregator_icclz1.csv
├── outage_labeling/
│   ├── latency_3inst_outage_labeled.csv
│   └── outage_windows.csv
├── dataset/
│   ├── thermal_yolo_labeled_dataset.csv
│   ├── thermal_yolo_labeled_dataset_with_vmagg.csv
│   ├── thermal_phase_schedule.csv
│   └── thermal_yolo_dataset_summary.csv
├── plots/
├── logs/
├── thermal/
└── k8s/
```

重要輸出：

- `raw_latency/*_raw.csv`
  - 原始 request-level latency。

- `metrics/gpu_smi_<node>.csv`
  - GPU temperature、power、utilization、memory、SM clock、memory clock、pstate。

- `metrics/vm_aggregator_<node>.csv`
  - VictoriaMetrics / Netdata / Kubernetes / DCGM 聚合後的監控欄位。
  - 欄位會以 `vmagg.*` 形式 flatten。
  - `collector_ok=0` 代表 wrapper / subprocess 層失敗。
  - `vmagg.collector_status=ok` 代表 aggregator 本身成功收集。
  - `vmagg.collector_status=error` 代表 aggregator 有正常輸出 JSON，但 VM/metrics 查詢失敗或部分前置步驟失敗。
  - 分析時建議優先使用 `vmagg.collector_status=ok` 的 rows；`error` rows 可視為 monitoring gap，不應直接解讀為 workload outage。

- `dataset/thermal_yolo_labeled_dataset.csv`
  - latency + thermal phase + outage/service label + GPU SMI。

- `dataset/thermal_yolo_labeled_dataset_with_vmagg.csv`
  - labeled dataset 再合併 VM aggregator 指標。
  - 一般後續訓練或分析優先看這個檔。

- `logs/vm_aggregator_collector.log`
  - VM aggregator collector 執行紀錄。

- `logs/vm_aggregator_merge_after_build.log`
  - `run_C` 每個 cycle build dataset 後的 VM aggregator merge log。

## 操作指令

### 1. 進入 repo 與啟用環境

```bash
cd ~/AutoScale
source iccl/bin/activate
```

### 2. 套用三個 YOLO deployment

```bash
kubectl apply -f experiments/yolo26_k8s/yolo26_3inst_icclz1.yaml

kubectl -n intent-lab rollout status deploy/yolo26n-focus
kubectl -n intent-lab rollout status deploy/yolo26n-bg-1
kubectl -n intent-lab rollout status deploy/yolo26n-bg-2
```

### 3. 檢查服務

```bash
curl http://100.105.48.97:18081/healthz
curl http://100.105.48.97:18082/healthz
curl http://100.105.48.97:18083/healthz
```

### 4. 五分鐘 smoke test

此範例主要檢查 YOLO latency client、health monitor、GPU telemetry 與 VM aggregator 是否能正常輸出。
未指定 `THERMAL_CMD` 時不會主動加熱；正式 thermal cycle 建議使用下一節的 `run_C` 範例。

```bash
cd ~/AutoScale

RUN_ID=B_thermal_yolo26_3inst_vmagg_smoke_$(date +%Y%m%d_%H%M%S)

WORKER_NODE=icclz1 \
WORKER_USER=icclz1 \
WORKER_IP=100.105.48.97 \
PRE_NORMAL_SEC=60 \
RAMP_UP_SEC=30 \
HIGH_HOLD_SEC=120 \
RAMP_DOWN_SEC=30 \
POST_NORMAL_SEC=60 \
FOCUS_INTERVAL=0.2 \
BG_INTERVAL=0.3 \
TARGET_TEMP_C=90 \
PLOT_TARGET_C=90 \
VM_AGGREGATOR_ENABLED=1 \
VM_AGGREGATOR_INTERVAL_SEC=5 \
VM_AGGREGATOR_AUTO_MERGE=1 \
VM_AGGREGATOR_PATH="$PWD/vm_aggregator.py" \
bash scripts/run_B_thermal_yolo26_3inst.sh "$RUN_ID"
```

### 5. 半天長跑範例

注意：`CYCLES=12` 中間不能有空格，不能寫成 `CYCLES= 12`。

```bash
cd ~/AutoScale
source iccl/bin/activate

OUTPUT_ROOT="$HOME/exp_runs/thermal90_yolo26_3inst_12cycles" \
RUN_ID_PREFIX="thermal90_yolo26_3inst" \
CYCLES=12 \
SLEEP_BETWEEN_CYCLES=300 \
PRE_NORMAL_SEC=600 \
RAMP_UP_SEC=60 \
HIGH_HOLD_SEC=1800 \
RAMP_DOWN_SEC=60 \
POST_NORMAL_SEC=600 \
FOCUS_INTERVAL=0.2 \
BG_INTERVAL=0.3 \
TARGET_TEMP_C=90 \
PLOT_TARGET_C=90 \
VM_AGGREGATOR_ENABLED=1 \
VM_AGGREGATOR_INTERVAL_SEC=5 \
VM_AGGREGATOR_AUTO_MERGE=1 \
VM_AGGREGATOR_MERGE_TOLERANCE_SEC=5 \
VM_AGGREGATOR_PATH="$PWD/vm_aggregator.py" \
bash scripts/run_C_thermal_yolo26_3inst_cycles.sh
```

這大約是 `12 * 57 分鐘 = 11.4 小時`，實際時間會受 setup、rollout、plot 影響。

### 6. 一天長跑範例

```bash
cd ~/AutoScale
source iccl/bin/activate

OUTPUT_ROOT="$HOME/exp_runs/thermal90_yolo26_3inst_24cycles" \
RUN_ID_PREFIX="thermal90_yolo26_3inst" \
CYCLES=24 \
SLEEP_BETWEEN_CYCLES=300 \
PRE_NORMAL_SEC=600 \
RAMP_UP_SEC=60 \
HIGH_HOLD_SEC=1800 \
RAMP_DOWN_SEC=60 \
POST_NORMAL_SEC=600 \
FOCUS_INTERVAL=0.2 \
BG_INTERVAL=0.3 \
TARGET_TEMP_C=90 \
PLOT_TARGET_C=90 \
VM_AGGREGATOR_ENABLED=1 \
VM_AGGREGATOR_INTERVAL_SEC=5 \
VM_AGGREGATOR_AUTO_MERGE=1 \
VM_AGGREGATOR_MERGE_TOLERANCE_SEC=5 \
VM_AGGREGATOR_PATH="$PWD/vm_aggregator.py" \
bash scripts/run_C_thermal_yolo26_3inst_cycles.sh
```

建議用 tmux：

```bash
tmux new -s yolo26_3inst_run
cd ~/AutoScale
source iccl/bin/activate
```

離開 tmux：

```text
Ctrl-b d
```

回到 tmux：

```bash
tmux attach -t yolo26_3inst_run
```

## 跑完後檢查

找最新 run：

```bash
OUTPUT_ROOT="${OUTPUT_ROOT:-$HOME/exp_runs}"
RUN_ID_PREFIX="${RUN_ID_PREFIX:-C_thermal_yolo26_3inst}"
ls -td "$OUTPUT_ROOT"/"${RUN_ID_PREFIX}"_cycle* | head
```

檢查 VM aggregator：

```bash
RUN_DIR=$(ls -td "$OUTPUT_ROOT"/"${RUN_ID_PREFIX}"_cycle* | head -n 1)

ls -lh "$RUN_DIR/metrics"
tail -n 20 "$RUN_DIR/logs/vm_aggregator_collector.log"
tail -n 20 "$RUN_DIR/logs/vm_aggregator_merge_after_build.log"
```

檢查 dataset：

```bash
ls -lh "$RUN_DIR/dataset"
```

快速看 rows / columns：

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path

run_dir = Path("$RUN_DIR").expanduser()
for name in [
    "thermal_yolo_labeled_dataset.csv",
    "thermal_yolo_labeled_dataset_with_vmagg.csv",
]:
    f = run_dir / "dataset" / name
    df = pd.read_csv(f)
    print(name, "rows =", len(df), "cols =", len(df.columns))
    if "collector_ok" in df.columns:
        print("collector_ok matched ratio =", df["collector_ok"].notna().mean())
    if "vmagg.collector_status" in df.columns:
        print(df["vmagg.collector_status"].value_counts(dropna=False).head())
PY
```

檢查 latency summary：

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path

run_dir = Path("$RUN_DIR").expanduser()
for f in sorted((run_dir / "raw_latency").glob("*_raw.csv")):
    df = pd.read_csv(f)
    x = pd.to_numeric(df["latency_ms_client"], errors="coerce").dropna()
    s = pd.to_numeric(df["server_latency_ms"], errors="coerce").dropna()
    print()
    print(f.name)
    print("client count =", len(x), "p50 =", x.quantile(.5), "p95 =", x.quantile(.95), "p99 =", x.quantile(.99), "max =", x.max())
    print("server count =", len(s), "p50 =", s.quantile(.5), "p95 =", s.quantile(.95), "p99 =", s.quantile(.99), "max =", s.max())
PY
```

## 常見問題

### 如何指定輸出資料夾名稱

`OUTPUT_ROOT` 控制輸出根目錄，`RUN_ID_PREFIX` 控制每個 cycle 的資料夾前綴：

```bash
OUTPUT_ROOT="$HOME/exp_runs/my_thermal_90C_run" \
RUN_ID_PREFIX="thermal90_yolo26_3inst" \
CYCLES=12 \
bash scripts/run_C_thermal_yolo26_3inst_cycles.sh
```

輸出範例：

```text
~/exp_runs/my_thermal_90C_run/thermal90_yolo26_3inst_cycle1_YYYYMMDD_HHMMSS/
```

如果只想改根目錄，也可用 `EXP_RUNS_DIR`；`OUTPUT_ROOT` 優先權較高。

### Ctrl-C 後 log 還在寫入

新版 `run_B` / `run_C` 已加入 `trap`，Ctrl-C / TERM 會清理目前 cycle 的背景程序。
若懷疑有舊版本殘留程序，可檢查：

```bash
ps -u "$USER" -o pid,ppid,pgid,stat,etime,cmd | \
  egrep 'run_C_thermal|run_B_thermal|collect_vm_aggregator|vm_aggregator|kubectl.*port-forward|yolo26_latency|run_cycle_from_master'
```

若只看到 `grep` / `egrep` 自己，代表沒有殘留程序。

### 手動 port-forward 會跟 script 衝突嗎

會，如果使用相同 local port。`run_B` 預設會自行開：

```text
VictoriaMetrics: 127.0.0.1:18428 -> 8428
Netdata:         127.0.0.1:11999 -> 19999
```

跑實驗時建議讓 script 自己開 port-forward。若你已手動開好 port-forward，請關閉自動
port-forward 並明確指定 URL：

```bash
VM_AGGREGATOR_AUTO_PORT_FORWARD=0 \
VM_AGGREGATOR_VM_URL=http://127.0.0.1:18428 \
VM_AGGREGATOR_NETDATA_URL=http://127.0.0.1:11999 \
VM_AGGREGATOR_NETDATA_CHILD_URL=http://127.0.0.1:11999 \
VM_AGGREGATOR_NETDATA_PARENT_BASE_URL=http://127.0.0.1:11999 \
bash scripts/run_C_thermal_yolo26_3inst_cycles.sh
```

### `CYCLES= 12` 失敗

這是 shell syntax 問題。環境變數指定不能在 `=` 後面放空格：

```bash
CYCLES=12
```

### VM aggregator path 找不到

目前正確路徑是：

```bash
VM_AGGREGATOR_PATH="$PWD/vm_aggregator.py"
```

不要使用舊路徑：

```bash
$PWD/experiments/monitoring/vm_aggregator.py
```

### `collector_ok` 都是空或 0，或 `vmagg.collector_status=error`

優先看：

```bash
tail -n 50 "$RUN_DIR/logs/vm_aggregator_collector.log"
tail -n 50 "$RUN_DIR/logs/vm_aggregator_vm_port_forward.log"
tail -n 50 "$RUN_DIR/logs/vm_aggregator_netdata_port_forward.log"
```

欄位意義：

- `collector_ok=0`
  - `collect_vm_aggregator_csv.py` 呼叫 subprocess 失敗，或 aggregator stdout 不是合法 JSON。
- `collector_ok=1` 且 `vmagg.collector_status=error`
  - `vm_aggregator.py` 有正常輸出 JSON，但 VM/metrics 查詢失敗。
  - 這類 rows 應視為 monitoring gap，不應直接判成 workload outage。
- `collector_ok=1` 且 `vmagg.collector_status=ok`
  - 正常資料列。

可能原因：

- VictoriaMetrics service 無法 port-forward。
- Netdata service 無法 port-forward。
- `kubectl` context 不對。
- `NODE` / `WORKER_NODE` 對不到 monitoring labels。
- 手動執行 `python vm_aggregator.py` 但沒有先開 `VM_URL` 對應的 port-forward。

`WORKER_NODE=icclz1` 時，script 會在未手動指定的情況下使用
`NODE_EXPORTER_INSTANCE=100.105.48.97:9100`，避免每次依賴
`node_uname_info{job="node-exporter"}` discovery。

### 沒有 `thermal_yolo_labeled_dataset_with_vmagg.csv`

先確認原始 VM aggregator CSV 存在：

```bash
ls -lh "$RUN_DIR/metrics/vm_aggregator_"*.csv
```

手動 merge：

```bash
python experiments/thermal_analysis/merge_vmagg_into_thermal_dataset.py \
  --run-dir "$RUN_DIR" \
  --tolerance-sec 5
```

## 建議分析順序

1. 先看 `raw_latency/focus_inst1_raw.csv` 的 `latency_ms_client` 與 `server_latency_ms`。
2. 再看 `dataset/thermal_yolo_labeled_dataset.csv` 的 thermal phase labels。
3. 再看 `dataset/thermal_yolo_labeled_dataset_with_vmagg.csv` 中的 `vmagg.*` 欄位。
4. 比較 `server_latency_ms` 是否跟 GPU temp / SM clock / power 同步變化。
5. 如果只有 `latency_ms_client` 有 tail spike，優先檢查 network、queueing、healthz、outage windows。
