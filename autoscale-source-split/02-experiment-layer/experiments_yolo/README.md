# experiments_yolo

本目錄是 `02-experiment-layer` 的主要 YOLO 實驗入口，重點在：

- 用 k3s 上的 YOLO service 產生 request traffic
- 搭配 `icclz1` 上的 `gpu-tempctl-lab` 做 fan control / background GPU load
- 同步收集 `vm_aggregator`、`nvidia-smi`、`kubectl top` 與 thermal phase 資料

目前已對齊的環境為：

- worker node: `icclz1`
- worker IP: `140.113.179.6`
- worker SSH alias: `icclz1-gpu`
- worker repo: `/home/icclz1/gpu-tempctl-lab`
- VictoriaMetrics: `http://140.113.179.9:31888`
- Netdata: `http://140.113.179.9:32163`
- repo root: `/home/icclz2/Pre6G`
- Python venv: `/home/icclz2/Pre6G/iccl`

截至 `2026-06-03` 本輪已重新驗證：

- `intent-lab` namespace 已建立
- `icclz1` 已重新出現 `nvidia.com/gpu.shared: 4`
- `yolo26n-focus` / `yolo26n-bg-1` / `yolo26n-bg-2` 已在 `intent-lab` `Running`
- `18081` / `18082` / `18083` 的 `/healthz` 皆回 `200`
- 短版 baseline smoke test 已重新跑通
- `single_pod_serial/` 短版 smoke test 已重新跑通
- `saturation_multi_pod/` 短版 service-load smoke test 已重新跑通
- `single_pod_serial_fault_fan/` 短版 smoke test 已重新跑通
- `single_pod_bgload_fan_cycle/` 短版 smoke test 已重新跑通
- `thermal_analysis/run_cycle_from_master.sh` 短版 direct thermal cycle 已跑通
- `scripts/run_C_thermal_yolo26_3inst_cycles.sh` 短版 formal thermal cycle 已跑通
- `scripts/run_yolo26_singlepod_rate_sweep.sh` 短版 rate sweep 已跑通
- `scripts/run_yolo26_singlepod_async_rate_sweep.sh` 短版 async rate sweep 已跑通

截至 `2026-07-02`，`single_pod_bgload_fan_cycle` 已補上 forecasting-first 離線分析路徑：

- `vm_aggregator` / collector 會保存 VM query result sample timestamp / age，用於確認 VictoriaMetrics query lag 是否影響 10-30s early-warning。
- `offline_bgload_forecasting_analysis.py` 產生 thermal / clock / latency forecasting、residual anomaly、composite service degradation early-warning 報告。
- `offline_vm_load_forecasting.py` 先針對 GPU util、VRAM usage、CPU usage、RAM usage 做短期負載預測。
- `offline_load_residual_thermal_bridge.py` 將負載 forecast residual 接到 thermal degradation early-warning，比較 `thermal_only`、`load_residual_only`、`thermal_plus_load_residual`。
- 目前結果顯示 load residual 單獨不足以 early-warning；主要可用訊號仍是 GPU temperature / clock，load residual 目前應視為輔助 feature 與後續資料補強方向。

截至 `2026-07-02`，下一階段 open-loop / load-conditioned thermal framework 已建立為安全的 dry-run / preflight-first 流程：

- `common/open_loop_request_client.py` 使用 monotonic clock 固定 scheduled arrivals，明確區分 `offered_rps` 與 completed/success throughput。
- `openloop_load_thermal_campaign/openloop_campaign_runner.py` 目前定位為 normal-cooling planner / dry-run / preflight runner，產生 campaign matrix、manifest、preflight 與 raw data preservation check；cooling-constrained `--run-campaign` 在 executor 尚未完成前一律 fail closed。
- runner 另提供 guarded normal-only live smoke / normal-cooling calibration executor；必須同時指定 `--normal-only` 與 `CONFIRM_NORMAL_SMOKE=YES`，且不包含 fan、CoolerControl、cooling intervention 或 Kubernetes workload control。
- open-loop client 會同時輸出 arrival-binned offered-load summary 與 completion-binned realized service activity summary，避免把 scheduled-bin completion count 誤稱為 realized completed RPS。
- `offline_normal_load_calibration_analysis.py` 會比較候選 offered RPS 的 drop ratio、completion throughput、timeout/error rate、latency quantiles 與 GPU telemetry；不自動選定 low/medium/high。
- 下一個資料里程碑是單一 normal-only smoke 資料鏈驗證；通過後才做 normal-cooling calibration，再建立 replicated normal high-load baseline dataset。現在不應直接跑完整 36-run campaign、cooling-constrained、LSTM/TCN 或新的 residual model。
- Milestone 1 可從 `openloop_load_thermal_campaign/configs/normal_only_smoke.operator.template.json` 複製成 operator-reviewed config，並依 `docs/NORMAL_ONLY_SMOKE_OPERATOR_CHECKLIST.md` 檢查後再手動啟動。
- `2026-07-03` 已完成一次 normal-only smoke：`0.5 RPS / 60s / max-inflight 4`，30/30 requests 成功、無 drop/timeout、GPU max temp 53C。輸出位於 `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_082457/normal_smoke_20260703_082457/`。
- 同次 smoke 的 VM sidecar sample-age 已完成檢查：per-query sample age p95 約 `0.512s`、max 約 `1.000s`，可作為 10-30s early-warning 的候選 telemetry。先前摘要中的 `116.0` 是 `queries_recorded`，不是 116 秒 sample age。
- `2026-07-03` 已完成 normal-cooling calibration first pass：`0.5 / 1.0 / 1.5 RPS`，各 60s、`max-inflight 4`，三個 level 皆 completed，無 drop、timeout 或 error。GPU temp p95 約 `50C / 59C / 62C`，VM sample-age max 約 `0.385s / 0.491s / 0.761s`。輸出位於 `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_093605/`。
- Calibration first pass 只代表正常散熱下的初步可用 offered-load candidates；尚未自動選定正式 low/medium/high，也不能取代 replicated normal high-load baseline。下一步應做 replicate 或更細 RPS 掃描，再進入 normal-load residual false-alarm validation；仍不得直接跳 cooling-constrained。
- 同次 calibration 已完成 VM-derived telemetry 候選特徵檢查：226 個 numeric VM 欄位中，23 個可列為 primary load candidates，主要是 CPU load average、namespace CPU rate、RAM / memory working set。GPU util 與 VRAM usage 在此短校準中為常數或近常數，VM `gpu_util_avg` 也與 nvidia-smi util 不一致，因此暫不作 primary load feature。報告位於 `dryrun_20260703_093605/vm_feature_candidate_check/`。
- `2026-07-03` 已完成 replicated normal-cooling baseline first pass：`0.5 / 1.0 / 1.5 RPS` 各 3 次，共 9 個 normal-only runs，全部 completed，無 drop、timeout、error 或 abort。輸出位於 `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_095642/`。
- Replicated baseline 已建立 1 秒 load-conditioned dataset，共 540 rows，並完成 normal-only expected behavior baseline。正常資料中的 residual scale 初估為：GPU temp abs residual p95 約 `4.67C`、SM clock abs residual p95 約 `145 MHz`、latency p95 abs residual p95 約 `21.4 ms`。這是正常散熱下的 false-alarm / threshold 參考，不代表 cooling-constrained 或未知根因偵測已驗證。
- `docs/OPENLOOP_LOAD_THERMAL_CAMPAIGN_DESIGN.md` 記錄 normal-high-load vs cooling-constrained 的實驗設計、安全防護、telemetry gap 與不可主張範圍。
- `common/offline_load_conditioned_residual_analysis.py` 與 `common/offline_event_level_degradation_audit.py` 提供下一輪資料取得後的 residual bridge 與 event-level onset-only evaluation。
- 目前這是實驗框架與方法學防護，尚未執行 cooling-constrained 正式 campaign，也不宣稱未知根因泛化。

## 實驗場景

### 1. `single_pod_serial/`

場景：

- 只保留一個 focus YOLO pod
- 不跑 background service pod
- client 採 closed-loop serial request
- 觀察單 pod 穩定服務時的 latency / resource 基線

適合用途：

- 做 baseline
- 確認 image、service、monitoring、serial client 都正常

啟動：

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial/run_single_pod_serial_with_metrics.sh
```

短版 smoke test：

```bash
cd /home/icclz2/Pre6G
TARGET_MODE=pod DURATION=60 TIMEOUT_SEC=20 REPEAT=1 \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial/run_single_pod_serial_with_metrics.sh
```

另一路目前已重新驗證的 baseline runner 是：

```bash
cd /home/icclz2/Pre6G
DURATION=60 FOCUS_INTERVAL=0.1 BG_INTERVAL=0.2 WARMUP_N=10 \
bash autoscale-source-split/02-experiment-layer/scripts/run_A_normal_baseline_yolo.sh
```

本輪 `2026-06-02` 重跑結果：

- `rows=1423`
- `success_rate=100%`
- `client_mean_ms=41.836`
- `client_p95_ms=46.670`
- `server_mean_ms=16.570`

### 2. `single_pod_serial_fault_fan/`

場景：

- 只保留一個 focus YOLO pod
- 不跑 background service pod
- client 採 serial request
- worker fan 固定在低速（預設 `5%`）
- 觀察低風扇下的溫度上升與 latency 變化

適合用途：

- 做單 pod fault-fan 熱退化觀察
- 看溫度上升是否影響 `e2e_latency_ms` / `server_latency_ms`

啟動：

```bash
cd /home/icclz2/Pre6G
CC_PASSWORD='your_coolercontrol_password' \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial_fault_fan/run_single_pod_serial_fault_fan.sh
```

本輪 `2026-06-02` 重跑結果：

- `rows=235`
- `success_rate=100%`
- `client_mean_ms=42.322`
- `client_p95_ms=49.052`
- `server_mean_ms=16.746`

短版 smoke test：

```bash
cd /home/icclz2/Pre6G
NODE_SSH=icclz1-gpu TARGET_MODE=pod TIMEOUT_SEC=20 REPEAT=1 \
WARMUP_SECONDS=0 NORMAL_HOLD_SECONDS=0 FAULT_HOLD_SECONDS=10 VM_AGG_INTERVAL=1.0 \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_serial_fault_fan/run_single_pod_serial_fault_fan.sh
```

### 3. `single_pod_bgload_fan_cycle/`

場景：

- 只保留一個 focus YOLO pod
- 不跑 background service pod
- client 採 serial request
- worker 端另外開 torch matrix background GPU load
- fan 在 `GPU_DEFAULT` 與低速 fault mode 間切換
- 包含 `normal_hold`、`fault_hold`、`recovery_wait`

適合用途：

- 看有背景 GPU load 時的 thermal cycle
- 觀察 fan 切換與恢復對 latency / resource / temperature 的影響

啟動：

```bash
cd /home/icclz2/Pre6G
CC_PASSWORD='your_coolercontrol_password' \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh
```

本輪 `2026-06-02` 重跑結果：

- `rows=310`
- `success_rate=100%`
- `client_mean_ms=55.685`
- `client_p95_ms=64.100`
- `server_mean_ms=31.025`

短版 smoke test：

```bash
cd /home/icclz2/Pre6G
NODE_SSH=icclz1-gpu TARGET_MODE=pod TIMEOUT_SEC=20 REPEAT=1 \
CYCLES=1 NORMAL_HOLD_SECONDS=5 FAULT_HOLD_SECONDS=5 \
RECOVERY_STABLE_SECONDS=5 RECOVERY_MAX_SECONDS=20 WORKLOAD_HEADROOM_SECONDS=10 \
VM_AGG_INTERVAL=1.0 \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh
```

`run_single_pod_bgload_fan_cycle_loop.sh` 則是把上述單次實驗用 `CYCLES=1` 的方式反覆重跑，適合批次累積多個 run。

loop 啟動：

```bash
cd /home/icclz2/Pre6G
CC_PASSWORD='your_coolercontrol_password' \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle_loop.sh
```

新版 VM sample-age sanity run 建議保留 `DEBUG_OUTPUT=1`：

```bash
cd /home/icclz2/Pre6G
DEBUG_OUTPUT=1 CC_PASSWORD='your_coolercontrol_password' LOOP_GAP_SECONDS=300 \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle_loop.sh
```

`vm_aggregator_timeseries.csv` 會包含 `vmagg._debug.vm_query_sample_age_summary.*`；per-query metadata 會寫到同一 run 目錄的 `vm_aggregator_timeseries.vm_query_samples.jsonl`。

短版 loop smoke test：

```bash
cd /home/icclz2/Pre6G
CC_PASSWORD='your_coolercontrol_password' \
NORMAL_HOLD_SECONDS=5 FAULT_HOLD_SECONDS=5 \
RECOVERY_STABLE_SECONDS=5 RECOVERY_MAX_SECONDS=20 \
WORKLOAD_HEADROOM_SECONDS=10 LOOP_GAP_SECONDS=10 \
bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle_loop.sh
```

### 4. `saturation_multi_pod/`

場景：

- 使用 `nvidia.com/gpu.shared`
- 在 `icclz1` 上同時跑多個 YOLO pod
- 對應 task3 / shared-GPU service-load 實驗

目前已驗證：

- `icclz1` 已有 `nvidia.com/gpu.shared: 4`
- `yolo26_task3_saturation.yaml` 對應的 4-pod stack 可正常建立
- `run_task3_service_load_with_metrics.sh` 已完成短版 smoke test

本輪 `2026-06-02` 重跑結果：

- `rows=3118`
- `success_rate=100%`
- `client_mean_ms=76.477`
- `client_p95_ms=121.749`
- `server_mean_ms=25.342`

啟動：

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/02-experiment-layer/experiments_yolo/saturation_multi_pod/run_task3_service_load_with_metrics.sh
```

若要先確認 GPU sharing：

```bash
kubectl describe node icclz1 | grep -E 'nvidia.com/gpu|nvidia.com/gpu.shared'
```

## 執行前共同前提

### 1. 先 build / import YOLO image

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_workload
bash build_and_import_image_to_k3s.sh
```

目前正式支援的 image tag：

- `local/yolo26n:0.1`

歷史上曾出現 `0.5`，但這不再是目前建議的驗證或重建標準。

注意：若 pod 會排到 GPU worker，該 worker 的 k3s/containerd 也必須有相同 image。

補充：

- repo 正式 canonical path 是 `02-experiment-layer/yolo26_workload`
- `icclz1` 現場若仍保留 `~/yolo26_k8s`，可作為 legacy build source 協助匯入 `local/yolo26n:0.1`，但它不是目前 repo 文件的正式路徑

### 2. 確認 worker SSH 可用

```bash
ssh icclz1-gpu "echo ok"
```

### 3. 若會跑 fan-cycle 類實驗，確認 worker-side repo 在

```bash
ssh icclz1-gpu "ls /home/icclz1/gpu-tempctl-lab/fan_control_lab"
```

補充：

- 這台 `icclz2` 主機已重新建立 `icclz1-gpu` SSH alias
- worker-side `gpu-tempctl-lab` 已可由 master 端直接觸發

## 子目錄說明

- `common/`
  - 共用 request client、thermal runner、summary / plot helper
- `yolo_demo/`
  - 目前只有 `README.md`，作為歷史示意與說明，不是現場要另外啟動的實驗元件
- `single_pod_serial/`
  - 單 pod serial baseline
- `single_pod_serial_fault_fan/`
  - 單 pod + 低風扇 fault 模式
- `single_pod_bgload_fan_cycle/`
  - 單 pod + background GPU load + fan cycle
- `saturation_multi_pod/`
  - shared-GPU / task3 類多 pod service-load
- `yolo_demo/`
  - 展示/輔助用途，不是目前主驗證線

## 備註

- 目前 smoke test runner 的 `summary.txt` 已不再硬依賴 `pandas`
- 某些 `analyze_*.py` / `plot_*.py` 若缺 `pandas`，現在會是 non-blocking，不影響主流程驗證
- `single_pod_*` 類 workflow 在執行期間會暫時把 `yolo26n-bg-1` scale 到 `0`
  - 驗證結束後應恢復原本三實例 layout
