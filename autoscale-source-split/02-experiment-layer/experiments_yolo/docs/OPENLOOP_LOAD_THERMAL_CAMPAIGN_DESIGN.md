# Open-loop Load-Conditioned Thermal Campaign Design

## 研究目標

下一階段實驗不以 fan fault classifier 為核心，而是驗證：

```text
Load Tracking / Load Forecasting
-> Load-Conditioned Expected Behavior
-> Thermal / Clock / Latency Residual
-> Thermal-Performance Degradation Risk
```

核心問題：

```text
在相同或可比較的外部工作負載條件下，
GPU temperature、SM clock 與服務 latency 是否超出正常高負載下的合理預期？
```

## 現有能力 Audit

- `single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh` 會整合 focus pod、background deploy、VM aggregator、`nvidia-smi`、`kubectl top`、serial request client 與 fan-cycle thermal runner。
- 既有 fan-cycle phase 主要為 `normal_hold`、`fault_hold`、`recovery_wait`，fan/cooling intervention 是實驗控制與事件對齊 metadata。
- `common/request_client_serial.py` 是 closed-loop serial：下一筆 request 會等待上一筆完成，因此 RPS 與 latency 具機械耦合。
- `common/request_client_parallel.py` 可做平行請求，但不是嚴格 fixed-arrival open-loop；它仍可能受 response completion 與 sleep 行為影響。
- VM / DCGM / Netdata / thermal 相關資料可由 `vm_aggregator_timeseries.csv`、`vm_aggregator_timeseries.vm_query_samples.jsonl`、`nvidia_smi_gpu_1s.csv`、`thermal.csv` 或 worker telemetry 取得，實際欄位須以 run 目錄內容為準。
- `offline_forecasting_analysis/` 已建立 time-aligned thermal/clock/latency 分析、methodology audit、forecast baseline 與 row-level early-warning。
- `vm_load_forecasting_analysis/` 已針對 GPU/VRAM/CPU/RAM 做 load forecasting，但 VM-derived telemetry 若作 primary 10-30s warning feature，應保留 VM sample timestamp / age。
- `load_residual_thermal_bridge_analysis/` 已串接 load residual 與 thermal degradation，但基於舊 closed-loop fan-cycle 資料，不能作為 open-loop 泛化證明。

## 缺少的 Telemetry / 方法缺口

- 尚未確認每個 run 均有 P-state、throttle reason、performance-cap reason、power-limit state、GPU process-level metrics。
- 舊資料多為 closed-loop serial request，`completed RPS` 不能代表純外部 offered load。
- 現有高分 early-warning 可能受固定實驗流程、固定 degradation onset 與 label horizon 影響，正式驗證需 event-level onset-only audit。
- 需要 normal_cooling high-load 對照，才能回答「高負載本身」與「散熱受限造成 residual 異常」的差異。

## 新增元件

- `common/open_loop_request_client.py`
  - 使用 monotonic clock 固定排程 scheduled arrivals。
  - `offered_rps` 定義為每秒 scheduled arrivals。
  - 支援 bounded concurrency / max in-flight。
  - 到達 max in-flight 或 schedule miss 會明確記錄，不會靜默降低送件速率。
  - 每筆保留 scheduled/send/complete time、status、error type、E2E latency、server latency 欄位。
  - 每秒輸出 offered / launched / completed / success / fail / timeout / in-flight / backlog / latency quantiles。

- `openloop_load_thermal_campaign/openloop_campaign_runner.py`
  - 目前定位為 normal-cooling planner / dry-run / preflight runner，並提供 guarded normal-only live smoke / calibration executor。
  - 支援 `--dry-run`、`--preflight-only`、`--normal-only`。
  - cooling-constrained `--run-campaign` 必須 fail closed，顯示 executor not implemented 並回傳非零 exit code。
  - normal-only live smoke 使用 `--run-normal-smoke --normal-only`，且必須有 `CONFIRM_NORMAL_SMOKE=YES`。
  - normal-cooling calibration 使用 `--calibrate-normal --normal-only`，且必須有 `CONFIRM_NORMAL_SMOKE=YES`。
  - dry-run/preflight 不執行 fan control、CoolerControl、kubectl scale/restart/delete 或長時間 GPU stress。
  - 產生 `run_manifest.json`、`execution_plan.md`、`raw_data_preservation_check.json`。

- `common/offline_load_conditioned_residual_analysis.py`
  - 只以 normal_cooling rows 訓練 expected behavior。
  - primary feature 禁止 phase、fan mode、fan speed、intervention flag、t_rel_s、run/cycle/profile ID。
  - 輸出 per-target expected value、residual、robust residual z-score 與 composite risk score。

- `common/offline_event_level_degradation_audit.py`
  - onset-only early-warning evaluation。
  - 排除已 degraded 區段與 onset 後模糊 transition。
  - 輸出 event recall、missed-event rate、false alarms per healthy hour、warnings per event、warning precision、lead time。

## 實驗矩陣

主要比較單位：

```text
normal_cooling at workload level X
vs.
cooling_constrained at same workload level X
```

可配置 factor：

- Workload profile: `low`、`medium`、`high`
- Cooling condition: `normal_cooling`、`cooling_constrained`、`recovery_observation`
- Replicate: 多個獨立 run
- Optional: `natural_high_load_normal_cooling`

控制原則：

- YOLO model、request payload mix、image set、client max in-flight、background workload profile 必須相同。
- 唯一主要處置差異應是 cooling condition。
- fan mode / intervention 只作 metadata 與事件對齊，不進 primary operational model。
- 先做 normal-cooling calibration，再決定 low/medium/high 的 target offered RPS；不要將舊 closed-loop completed RPS 當成外部 demand。

## 安全防護

- cooling-constrained campaign 必須同時滿足 `--run-campaign` 與 `CONFIRM_EXPERIMENT=YES`，但目前 executor 尚未實作，因此即使有 `CONFIRM_EXPERIMENT=YES` 仍會 fail closed。
- normal-only live smoke/calibration 必須同時滿足 `--normal-only` 與 `CONFIRM_NORMAL_SMOKE=YES`。
- normal-only live executor 只允許讀取 telemetry、執行 open-loop request client、寫入本 run 的輸出；不包含 fan mode、CoolerControl、cooling intervention、background workload scale/restart/delete。
- operator 必須設定 `safety.operator_max_gpu_temp_c`；本文件不猜測設備安全溫度。
- cooling-constrained 流程開始前須記錄原始 cooling/fan 狀態。
- 結束、例外、中止時必須嘗試恢復 `GPU_DEFAULT`，並將恢復結果寫入 manifest。
- telemetry 缺失、溫度超限、服務完全失效、控制命令失敗時 fail closed。
- normal-only live smoke/calibration 若發生 missing GPU telemetry、temperature over limit、timeout/error burst、max-inflight saturation 或 request/telemetry output 缺失，必須寫入 `safety_abort_record.json` / `safety_abort_record.jsonl`。
- dry-run/preflight 不允許 fan control、CoolerControl、Kubernetes scale/restart/delete。

## 預期資料流

```text
open_loop_client_raw.csv
open_loop_client_arrival_1s_summary.csv
open_loop_client_completion_1s_summary.csv
vm_aggregator_timeseries.csv
vm_aggregator_timeseries.vm_query_samples.jsonl
nvidia_smi_gpu_1s.csv
worker_thermal_telemetry.csv
control_events.jsonl
run_manifest.json
safety_abort_record.json
telemetry_availability_summary.json
```

Arrival-binned summary 以 scheduled arrival time 分桶，用於 offered-load accounting。Completion-binned summary 以 response completion time 分桶，用於 realized service activity。兩者不可混用；scheduled-bin 的 completed count 不可命名為 realized completed RPS。

分析流程：

```text
offered load / background load features
-> normal_cooling expected thermal/clock/latency model
-> residual distribution under normal high load
-> residual distribution under cooling_constrained
-> event-level thermal-performance risk evaluation
```

## 驗證策略

- 禁止 random row split、shuffle split、同一 run 相鄰點跨 train/test。
- threshold、normal baseline、feature scaling、residual distribution 只由 training normal-cooling data 建立。
- 優先使用 chronological hold-out by run、GroupKFold by run、leave-one-run-out、leave-one-load-profile-out。
- 必須包含 time-only negative control、offered-load-only baseline、thermal-only ablation、thermal + service-history ablation。
- Event-level scorer 只負責 warning/event matching；若未提供 model manifest 或 feature list artifact，不得宣稱已完成 feature leakage audit。

## Normal-Cooling Calibration

Calibration 不應作為第一個 live step。下一個實際資料里程碑必須先是單一 normal-only smoke，用保守低 offered RPS、短時間執行，目的只驗證資料鏈：

```text
open-loop scheduler
-> YOLO endpoint
-> arrival/completion logs
-> VM/DCGM/thermal telemetry
-> manifest / safety record
```

Smoke 前 operator 必須人工確認：

- `operator_max_gpu_temp_c` 已依現場設備政策設定。
- endpoint、image payload、node 與 GPU 身分正確。
- 沒有其他非預期 GPU workload。
- telemetry collector 可取得 GPU temperature、SM clock、power、utilization。
- normal-only config 不含任何 fan / CoolerControl / K8s control action。

Smoke 啟動條件維持：

```text
--run-normal-smoke
--normal-only
CONFIRM_NORMAL_SMOKE=YES
```

Smoke 成功判定不看模型分數，只看資料可信度：

- scheduled arrivals 與設定 target RPS 一致。
- `dropped_max_inflight` 接近 0。
- completion-binned throughput 與 completion timestamp 合理。
- 無持續 timeout / error burst。
- GPU temperature 未接近 operator 上限。
- SM clock 無無法解釋的異常降頻。
- GPU、VM、request log timestamp 可對齊。
- raw log、arrival/completion summary、manifest、safety record 齊全。

若 smoke 出現 timeout、drop 或 telemetry gap，不得提高 RPS；應先修資料鏈或 client saturation 問題。

`calibration.candidate_offered_rps` 可列出多個候選 offered RPS。runner 會逐一短時間執行 normal-cooling open-loop client，並輸出每個 candidate 的 request summary、telemetry availability 與 safety/abort record。

校準分析由 `offline_normal_load_calibration_analysis.py` 完成，輸出每個 candidate 的 offered RPS median、drop ratio、completion throughput、timeout/error rate、latency p50/p95/p99、GPU temperature、SM clock、power 與 utilization。

校準工具不自動選定 low/medium/high；operator 必須人工檢視後決定正式 workload profiles。

Calibration 通過後才建立 replicated normal high-load dataset，先驗證：

```text
normal_cooling + high offered load
-> load-conditioned expected behavior
-> temperature / clock / latency residual
```

核心檢查是高 offered load 但散熱正常時 residual 是否維持低值，且 false alarm 可接受。只有通過後才進入 matched cooling-constrained pilot。

目前里程碑順序：

1. Normal-only smoke 資料鏈驗證
2. Normal-cooling calibration
3. Replicated normal high-load dataset
4. Normal-load residual false-alarm validation
5. Matched cooling-constrained pilot

目前禁止事項：

- 不直接跑完整 36-run campaign。
- 不先跑 cooling-constrained。
- 不先訓練 LSTM / TCN。
- 不先改 residual model。
- 不將 completed RPS 當 external offered load。

## 不可主張的範圍

- 不可宣稱已證明跨環境泛化。
- 不可宣稱已證明未知根因偵測成功。
- 不可宣稱已證明 NVIDIA thermal throttling mechanism，除非補齊且驗證 throttle reason / P-state / performance-cap telemetry。
- fan intervention 是實驗控制與事件對齊參考，不是 primary operational model feature。
- closed-loop 舊資料可支持時序現象與方法開發，但不足以單獨證明 open-loop offered-load 條件下的泛化 early-warning。
