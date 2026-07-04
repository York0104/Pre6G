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
- 同批 dataset 已完成初版 held-out normal residual false-alarm validation，不使用 random row split。初版結果顯示 `residual baseline unstable across runs` 與 `feature quality issue`：0.5 RPS 的 held-out composite false alarm 較高，且 nvidia-smi GPU util 與 VM GPU util corr 約 `0.074`、median abs diff 約 `21%`。因此目前不應直接安排 cooling-constrained pilot，應先排查低 RPS warm-up / run state 差異與 VM GPU util 品質。
- 已完成 measurement-validity and run-state audit。結論分類為 `low-RPS measurement sparsity`、`warm-up / run-state effect`、`telemetry semantic mismatch`、`true normal baseline instability`。1 秒 latency p95/p99 在 `0.5 / 1.0 / 1.5 RPS` 下每 bin completion 中位數僅 `0.5 / 1.0 / 1.5`，不足以作為穩定 tail-latency evidence；所有 run manifest 也缺少 explicit replicate 與 warm-up metadata。VM `gpu_util_avg` 有 5/9 runs 判定為 mismatched semantic metric、4/9 為 insufficient evidence。報告位於 `dryrun_20260703_095642/measurement_validity_audit/`。
- 已完成 quality-aware rerun：`build_openloop_load_conditioned_dataset.py` 現在新增 10 秒 rolling latency target，`min_latency_samples=5`，樣本不足時不產生正式 rolling p95；VM `gpu_util_avg` 預設排除於 primary feature candidates，並在 VM candidate check 中標記為 `telemetry_semantic_pending`。held-out validator 不再用 run_id 排序推估 replicate；因 manifest 缺 explicit replicate，正式 validation 只執行 9-fold `Leave-One-Run-Out`，`Leave-One-Replicate-Per-Load-Level-Out` 被標記 skipped。quality-aware 結論仍為 `residual baseline unstable across runs`，0.5 RPS composite risk median false alarms 約 `300/h`，但 rolling latency p95 debounced episode count 已降為 0。輸出位於 `dryrun_20260703_095642/heldout_normal_residual_validation_quality_aware/` 與 `measurement_validity_audit_quality_aware/`。
- 已完成 Normal Baseline v2 collection readiness。新增 v2 manifest/data contract，下一輪 normal-cooling open-loop run 必須保存 `campaign_id`、`replicate_id`、`run_order`、warm-up / measurement / post-observation boundary timestamp、endpoint/model/image-set hash、node/GPU UUID、background workload state、telemetry availability 與 sample-age summary。缺少核心 metadata 的 run 會被 dataset builder 標記 `analysis_ineligible`，不得進正式 held-out validation。v2 readiness audit 已確認既有 9-run v1 dataset 全部因 manifest gap 被排除於 formal validation，輸出位於 `dryrun_20260703_095642/normal_baseline_v2_readiness_dataset_audit/`。
- v2 primary feature schema：`target_offered_rps`、`inflight_count_max`、`client_backlog_or_schedule_miss` 與 verified background workload state；`target_offered_rps` 與 `scheduled_request_count` 不得同時作 primary predictors。VM `gpu_util_avg` 維持 `telemetry_semantic_pending`，nvidia-smi/DCGM GPU telemetry 僅作 GPU state reference 或 target。
- `2026-07-03` 已取得第一筆有效 Normal Baseline v2 normal-cooling run：`dryrun_20260703_153757/normal_smoke_20260703_153757/`。設定為 `0.5 RPS`、`60s warm-up + 300s measurement + 30s post-observation`，`195/195` requests 成功、無 drop/timeout/error，VM sample-age max 約 `1.001s`，GPU max temp `62C`。v2 dataset audit 位於 `dryrun_20260703_153757/normal_baseline_v2_dataset_audit/`，390 rows 中有 300 個 formal eligible measurement-window rows。這只是第一筆有效 v2 baseline，尚不足以做 held-out cross-run validation；下一步需補同條件 replicate。
- 已準備 Normal Baseline v2 `r02` / `r03` config，兩者 dry-run 與 preflight-only 均通過且無 warnings/errors。config 位於 `openloop_load_thermal_campaign/configs/normal_baseline_v2_r02.icclz2.draft.json` 與 `normal_baseline_v2_r03.icclz2.draft.json`。
- 已取得 Normal Baseline v2 `r02` / `r03` 並合併 r01-r03 做 held-out validation。三個 v2 runs 均為 `0.5 RPS`，各 `195/195` success、無 fail/drop/timeout，各有 `300` formal eligible measurement rows。combined dataset 位於 `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_combined_r01_r03/`。validation 已啟用 `Leave-One-Run-Out` 與 `Leave-One-Replicate-Per-Load-Level-Out`，但結論仍為 `insufficient normal replicates` 與 `residual baseline unstable across runs`，主要因 r02 rolling latency p50/p95 與 composite risk 出現 debounced episodes；因此尚不應進 cooling-constrained pilot。
- 已新增 `docs/SINGLE_POD_BGCYCLE_AVAILABILITY_FAILURE_NOTE.md`，明確記錄 aggressive `single_pod_bgload_fan_cycle` 若出現 liveness restart、connection refused burst 與低 success rate，應定位為 availability failure / resilience threshold，不應寫成乾淨的 thermal-induced latency degradation。
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

## Open-loop Normal Baseline v2 Status

目前已取得第一批 normal-cooling v2 open-loop replicated dataset：

- `r01/r02/r03`
- target offered load: `0.5 RPS`
- formal measurement window: `300s` per run
- request result: measurement window 皆為成功 completion，無 max-inflight drop / timeout burst
- combined dataset: `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_combined_r01_r03/`

Held-out normal residual validation 已完成，但結論是 `insufficient normal replicates; residual baseline unstable across runs`。後續 r02 shift diagnosis 顯示 r02 的 residual episodes 主要來自 normal run-to-run latency baseline shift：rolling latency p50 跨 replicate spread 約 `27.75 ms`，但 GPU temperature p50 spread 約 `1.0 C`、SM clock p50 spread 約 `13 MHz`，不足以解讀為 thermal degradation。

因此目前不應進入 cooling-constrained pilot。下一步應先補更多相同 offered RPS 的 normal-cooling v2 replicate，或延長 measurement duration 後重跑 held-out normal residual validation。

2026-07-03 已補充 r04/r05/r06 三筆相同條件 normal-cooling v2 replicate：

- output roots:
  - `dryrun_20260703_194100/normal_smoke_20260703_194100` (`r04`)
  - `dryrun_20260703_194753/normal_smoke_20260703_194753` (`r05`)
  - `dryrun_20260703_195451/normal_smoke_20260703_195451` (`r06`)
- combined dataset: `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_combined_r01_r06/`
- r04/r05/r06 皆為 `195/195` successful completions，無 safety abort，VM sample age max 約 `0.63-1.01s`，GPU max temp `62C`
- held-out validation: composite risk max debounced episode count 降到 `1`，但 r02 rolling latency p50 shift 仍存在
- current decision: normal baseline 可用於方法開發，但 latency residual threshold 尚未達正式穩定；cooling-constrained pilot 仍暫緩

Service-state normalization sensitivity 已補上：

- output: `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_combined_r01_r06/service_state_normalized_validation*/`
- 60s healthy calibration 仍無法移除 r02 rolling latency p50 episode
- 120s / 180s calibration 可移除 r02 rolling latency p50 episode
- interpretation: r02 比較像 normal service-state transition/ramp，而不是固定 offset 或 thermal degradation

Long normal-cooling r07 已完成：

- config: `openloop_load_thermal_campaign/configs/normal_baseline_v2_long_r07.icclz2.draft.json`
- run: `dryrun_20260703_211041/normal_smoke_20260703_211041`
- analysis: `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_long_r07_analysis/`
- request result: `555/555` successful completions
- formal measurement: `900s` after `180s` warm-up
- drift: rolling latency p50 first-to-last third about `-4.46 ms`; p95 about `+0.66 ms`; GPU temp / SM clock median no material drift
- current decision: collect at least two more long normal-cooling replicates before cooling-constrained pilot

Long normal-cooling r08/r09 也已完成，形成 r07-r09 三筆 long baseline：

- r08: `dryrun_20260703_214750/normal_smoke_20260703_214750`
- r09: `dryrun_20260703_220649/normal_smoke_20260703_220649`
- combined analysis: `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_long_r07_r09_analysis/`
- 每筆皆為 `555/555` successful completions，無 safety abort
- VM / nvidia-smi telemetry 完整，GPU max temp `62-63C`
- long-run 內部 drift 小：三筆的 GPU temp / SM clock median first-to-last third delta 皆為 `0`
- 但 raw held-out latency residual 仍對跨 run service baseline level 敏感，r08 會被誤判為整段 latency p50 anomaly
- 180s run-local healthy calibration 後：
  - rolling_latency_p50 episodes: `0`
  - rolling_latency_p95 episodes: `0`

目前最嚴謹結論：long normal protocol + run-local healthy calibration 才適合作為 matched cooling-constrained pilot 的 normal baseline；不應使用未校正的 raw cross-run latency residual 直接做主要告警。

Matched pilot readiness gate 已補上：

- contract: `docs/MATCHED_COOLING_CONSTRAINED_PILOT_CONTRACT.md`
- audit tool: `common/offline_matched_pilot_readiness_audit.py`
- output: `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/matched_pilot_readiness_audit/`
- decision: `method_ready_but_live_cooling_executor_still_fail_closed`

這表示：方法學上可開始設計 matched cooling-constrained pilot，但 live cooling executor 仍故意 fail-closed；目前不可直接跑 `--run-campaign`。

Matched cooling-constrained pilot preflight/recovery framework 已補上：

- config template: `openloop_load_thermal_campaign/configs/matched_cooling_constrained_pilot.operator.template.json`
- runner 允許對該 config 執行 `--dry-run` / `--preflight-only`
- preflight 會輸出 `matched_cooling_pilot_preflight.json`、`matched_cooling_recovery_plan.json`、`control_event_log.dryrun.jsonl` 與 `MATCHED_COOLING_PILOT_PREFLIGHT.md`
- preflight 會檢查 r07-r09 readiness evidence、`180s` run-local healthy calibration、`900s` measurement、`GPU_DEFAULT` restore target、operator safety threshold 與 matched offered-load metadata
- live `--run-campaign` 已接到 cooling-only SSH supervisor，但必須同時具備 `CONFIRM_EXPERIMENT=YES` 與 `CC_PASSWORD`
- live pilot 不使用舊 `single_pod_bgload_fan_cycle` runner，不啟動 torch background GPU load，不做 Kubernetes scale/restart/delete
- 目前尚未取得正式 cooling-constrained pilot dataset；執行後需再做 normal-control vs cooling-constrained residual comparison

`2026-07-04` 已完成第一筆 matched cooling-constrained live pilot：

- run root: `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260704_114703_944629/`
- run dir: `matched_cooling_pilot_20260704_114703_956095`
- execution: open-loop `0.5 RPS` + cooling-only SSH supervisor
- no legacy fan-cycle runner, no torch background GPU load, no Kubernetes scale/restart/delete
- request result: `555/555` success, no max-inflight drop, no timeout/error burst
- thermal result: warm-up temp p50/max `56/61C`; cooling-constrained temp p50/max `84/88C`
- clock result: warm-up SM clock p50 `1923 MHz`; cooling-constrained p50/min `1582/1556 MHz`
- restore: `GPU_DEFAULT` restore succeeded
- residual analysis: `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/matched_cooling_pilot_20260704_114703_residual_analysis/`
- formal residual rows: normal-control `2700` rows（r07-r09, 3 x 900s）；cooling-constrained `900` rows
- formal residual result:
  - GPU temperature residual median: `+24.83C` under cooling-constrained
  - SM clock residual median: `-354.31 MHz` under cooling-constrained
  - rolling latency p50 residual median: `+13.30 ms` under cooling-constrained
  - composite risk p95: normal `57.60`; cooling-constrained `104.22`
- interpretation: 第一筆 pilot 已直接觀察到相同 offered load 下的 temperature rise、SM clock reduction 與 mild latency increase，且未出現 availability collapse。這是 matched pilot evidence；仍不能宣稱未知根因泛化、正式 early-warning performance 或已證明 NVIDIA thermal throttling mechanism。

`2026-07-04` 已補齊 matched cooling-constrained pilot replicate，共三筆：

- additional run dirs:
  - `dryrun_20260704_124944_233391/matched_cooling_pilot_20260704_124944_246463`
  - `dryrun_20260704_130851_818125/matched_cooling_pilot_20260704_130851_832320`
- all cooling replicates: `555/555` successful completions, no max-inflight drop, no timeout/error burst
- GPU max temperature: `87-88C`; `GPU_DEFAULT` restore succeeded for all runs
- replicated residual analysis:
  - `results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/matched_cooling_pilot_replicates_20260704_analysis/`
- formal residual result over 3 normal-control vs 3 cooling-constrained runs:
  - cooling GPU temperature residual median: `+24.83C`
  - cooling SM clock residual median: `-309.81 MHz`
  - cooling rolling latency p50 residual median: `+14.24 ms`
  - cooling rolling latency p95 residual median: `+17.75 ms`
  - composite risk p95: normal `57.60`; cooling-constrained `104.48`
  - composite risk episodes: normal `0/3` runs; cooling-constrained `3/3` runs
- current interpretation: matched cooling-constrained replicate evidence now supports a controlled thermal-performance residual comparison at `0.5 RPS`. It still remains single GPU / single workload / single offered-load / single cooling-profile evidence, so event-level early-warning and generalization claims remain future work.
