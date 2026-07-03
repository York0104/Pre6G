# Monitoring Rebuild Progress

Date: 2026-06-24
Workspace: `/home/icclz2/Pre6G`
Host: `icclz2`
Control plane IP: `140.113.179.9`

## Summary

目前這台主機上的正式重建主線已完成到：

- `k3s` control-plane 已建立並可正常提供 Kubernetes API
- `monitoring-rebuild/` 核心監控 stack 已部署完成
- GPU auto-discovery / device plugin / `dcgm-exporter` 已恢復
- `autoscale_api` 可在 host-side Python venv 啟動
- `cluster-dashboard` 可在本機以 Node 22 啟動與 build
- `autoscale_api` 與 dashboard 已可由 user-level systemd 常駐啟動
- dashboard 已可顯示一般 `k3s` nodes 與 external nodes
- `2026-06-24` 已完成 `Fan-Cycle Experiment` host-side rebuild：
  - 修正 experiment path/root 對齊
  - 新增 API `fan-cycle` run `status/start/stop`
  - 將 YOLO demo / fan-cycle runtime 參數抽成 `PRE6G_EXPERIMENT_*`
  - dashboard 頁面可在無 completed run 時仍顯示控制區塊
- `2026-06-25` 已完成 `Gemma 4 vLLM` workload monitoring 第一版：
  - `vmagent` 新增 `ai-serving` pod auto-discovery scrape job
  - `autoscale_api` 新增 workload schema / adapter / router
  - dashboard 新增 `LLM Workloads` 區塊
  - live Pod `/metrics` 與 VictoriaMetrics 中的 `vllm:*` 指標已確認存在
  - live `autoscale-api` hostPath deployment 已重啟套用 workload API
  - live `GET /api/v1/workloads` 與 `/api/v1/workloads/ai-serving/gemma4-e2b-vllm/status` 已驗證可用
  - 成功送出 inference request 後，live workload API 已回傳非零 TPS
- `2026-07-02` 已完成 `LLM Serving Lab` benchmark 路徑收斂：
  - `Serving Benchmark` 正式定義為對 live `Gemma 4 vllm serve` 執行官方 `vllm bench serve`
  - `Serving Benchmark` 對應 `Serving Capacity View`
  - `Offline Throughput Benchmark` 正式定義為對 `icclz1` dedicated target 執行官方 `vllm bench throughput`
  - `Offline Throughput Benchmark` 對應 `Hardware Capacity View`
  - `icclz1` dedicated target 第一版模型已收斂為 `Qwen/Qwen2.5-1.5B-Instruct`
  - `autoscale_api` 與 `k3s` 文檔已補齊 offline benchmark target env / RBAC / manifest
  - dedicated target pod 已實際部署到 `icclz1`
  - host-side `autoscale_api` / dashboard 已重啟套用新配置
  - live `POST /api/v1/llm-lab/offline-throughput` 已實測打通 control path
  - 目前 benchmark 真正執行仍被 `vllm/vllm-openai:v0.23.0` 對 `GTX 1080 Ti` 的 CUDA forward-compatibility 問題阻塞
  - 因此 `GTX 1080 Ti (CC 6.1)` 已被正式排除為目前平台下的受支援 offline throughput target
  - 後續正式路徑建議改為 `RTX 4090 dedicated benchmark target`，代價是單卡環境下 live serving 與 offline throughput 必須分時切換
- `2026-07-02` 已完成 `KPI-A2-1 GPU thermal/load forecasting offline analysis` 第一版：
  - `vm_aggregator` 已補上 VM instant query result sample timestamp / age audit 欄位
  - `collect_vm_aggregator_csv.py` 已將 per-query VM sample metadata 拆到 `vm_aggregator_timeseries.vm_query_samples.jsonl` sidecar，避免主 CSV 過大
  - 新版 fan-cycle sanity runs 已確認 `vmagg._debug.vm_query_sample_age_summary.*` 與 sidecar 正常落盤
  - 已新增 thermal / clock / latency forecasting-first 離線分析腳本
  - 已新增 VM 主要負載預測腳本，目標為 GPU util、VRAM usage、CPU usage、RAM usage
  - 已新增 load residual 接續 thermal degradation early-warning bridge 實驗
  - 目前 bridge 結論：`load_residual_only` 尚不足以 early-warning，主要可用訊號仍是 thermal / clock；`thermal_plus_load_residual` 可作為下一輪比較，但尚不能宣稱未知根因泛化
  - 主要輸出目錄：
    - `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/offline_forecasting_analysis/`
    - `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/vm_load_forecasting_analysis/`
    - `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/load_residual_thermal_bridge_analysis/`
- `2026-07-03` 已完成 open-loop normal-only smoke 資料鏈驗證：
  - 設定為 `0.5 RPS / 60s / max-inflight 4`，不含 fan、CoolerControl、cooling intervention 或 Kubernetes workload control
  - 30/30 requests 成功，無 max-inflight drop、無 timeout/error burst，GPU max temp 53C
  - request raw log、arrival-binned summary、completion-binned summary、nvidia-smi telemetry、VM sidecar、manifest 與 safety record 皆已落盤
  - VM sidecar sample-age p95 約 0.512s、max 約 1.000s；先前 summary 中 116.0 來自 `queries_recorded` 誤納入 sample-age 計算，已修正
  - 下一步可做 normal-cooling calibration；仍不可直接跳 cooling-constrained campaign 或使用本次單一 smoke 宣稱 high-load baseline 已建立
- `2026-07-03` 已完成 normal-cooling calibration first pass：
  - 候選 offered RPS 為 `0.5 / 1.0 / 1.5`，各 60 秒、`max-inflight 4`、正常散熱、無 fan / CoolerControl / Kubernetes 控制
  - 三個 level 皆 completed，scheduled/completed 分別為 `30/30`、`60/60`、`90/90`，drop ratio、timeout rate、error rate 皆為 0
  - latency p95 約 `191.95 / 195.68 / 201.25 ms`
  - GPU temp p95 約 `50 / 59 / 62 C`，SM clock median 約 `1949 / 1936 / 1923 MHz`
  - VM sample-age max 約 `0.385 / 0.491 / 0.761 s`，皆為 `ok_for_10_30s_warning`
  - 此結果只支持初版 normal-cooling candidate 可用；尚未完成 replicated normal high-load baseline，也尚未進入 cooling-constrained pilot
  - 已新增 VM-derived telemetry candidate check：226 個 numeric VM 欄位中，23 個可作 primary load candidate，主要集中於 CPU load average、namespace CPU rate、RAM / memory working set
  - VM `gpu_util_avg` 與 VRAM usage 在此短 calibration 中為常數或近常數，且 VM `gpu_util_avg=0` 與 nvidia-smi util 不一致；下一輪 load-conditioned model 不應把該 VM GPU util 欄位當 primary feature，需以 nvidia-smi/DCGM 交叉驗證
- `2026-07-03` 已完成 replicated normal-cooling baseline first pass：
  - `0.5 / 1.0 / 1.5 RPS` 各 3 次，共 9 個 normal-only runs；全部 completed，無 drop、timeout、error 或 safety abort
  - 既有 fan-cycle raw RUN_ID directories preservation check 通過，未修改 raw results
  - 建立 `openloop_load_conditioned_1s_dataset.csv`，共 540 rows，未包含 phase/fan/intervention/run/cycle 作為 primary features
  - 完成 normal-only load-conditioned expected behavior baseline；正常資料 residual scale 初估為 GPU temp abs residual p95 約 4.67C、SM clock abs residual p95 約 145MHz、latency p95 abs residual p95 約 21.4ms
  - 這只建立 normal-load false-alarm / threshold 參考；尚未執行 cooling-constrained pilot，也尚未宣稱未知根因泛化
- `2026-07-03` 已完成 held-out normal residual false-alarm validation：
  - 初版驗證策略包含 9-fold Leave-One-Run-Out 與 3-fold Leave-One-Replicate-Per-Load-Level-Out；沒有 random row split，也沒有讓同一 run 的相鄰秒級資料跨 train/test
  - 每 fold 只用 training normal-cooling runs fit expected behavior model，並只用 training residual distribution 建 threshold
  - 結論分類為 `residual baseline unstable across runs` 與 `feature quality issue`
  - 主要風險：0.5 RPS held-out composite false alarms 偏高，最高 median composite false alarms 出現在 offered_rps=0.5，並非隨 offered load 單調上升
  - VM GPU util 與 nvidia-smi GPU util 品質不一致：corr 約 0.074、median absolute difference 約 21%；下階段不得將該 VM GPU util 當 primary feature
  - 因此目前不應直接進 matched cooling-constrained pilot；需先排查 low-RPS warm-up / run-state 差異、強化 feature selection，或增加更穩定的 normal baseline replicates
- `2026-07-03` 已完成 normal baseline measurement-validity and run-state audit：
  - latency sample sufficiency：完整 60-second bins 納入後，`0.5 / 1.0 / 1.5 RPS` 每 bin completion 中位數為 `0.5 / 1.0 / 1.5`，`min_latency_samples=5` 下 sufficient_fraction 皆為 0；1-second p95/p99 不可作為穩定 tail-latency evidence
  - warm-up/run-state：使用前 10 秒 measurement eligibility mask；held-out exceedance 有起始區段集中現象，且 0.5 RPS 有 debounced composite / GPU temp / SM clock episodes
  - replicate identity：9 個 run manifest 皆缺 explicit replicate 與 warm-up metadata，已標記 `replicate_missing;warmup_metadata_missing`；不得以 run_id 排序當正式 replicate metadata
  - VM GPU utilization semantic audit：5/9 runs 判定 `mismatched semantic metric`、4/9 為 `insufficient evidence`；sidecar 有 PromQL/sample-age，但無完整 labels/unit/aggregation-window metadata
  - 結論分類：`low-RPS measurement sparsity`、`warm-up / run-state effect`、`telemetry semantic mismatch`、`true normal baseline instability`
  - 因此在修正 measurement validity 前，不應啟動 cooling-constrained pilot；下一步應改用較長 rolling latency window、補 manifest replicate/warm-up metadata、修 VM GPU util semantic capture，並重新驗證 held-out normal false alarms
- `2026-07-03` 已完成 quality-aware held-out normal residual validation rerun：
  - `build_openloop_load_conditioned_dataset.py` 新增 10 秒 rolling latency target，`min_latency_samples=5`；低樣本 window 直接標為 insufficient，不再把 1-second single-completion p95 當正式 tail-latency target
  - dataset builder 預設排除 VM `gpu_util_avg`，直到 semantic / timestamp / unit 判定完成；`offline_vm_feature_candidate_check.py` 也將該欄位標為 `telemetry_semantic_pending`
  - held-out validator 不再用 run_id 排序推估 replicate；因 9 個 run manifest 皆缺 explicit replicate，正式 validation 只執行 9-fold Leave-One-Run-Out，replicate-per-load split 被標記為 skipped
  - 新輸出目錄：
    - `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_095642/load_conditioned_dataset_quality_aware/`
    - `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_095642/heldout_normal_residual_validation_quality_aware/`
    - `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_095642/measurement_validity_audit_quality_aware/`
    - `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_095642/vm_feature_candidate_check_quality_aware/`
  - quality-aware 結論仍為 `residual baseline unstable across runs`：0.5 RPS composite risk median false alarms 約 `300/h`，但 rolling latency p95 的 debounced episode count 已降為 0；不應進 cooling-constrained pilot
  - 下一步不是新模型，而是補正式 manifest metadata（replicate、operator-defined warm-up）、延長 normal baseline run 或提高 latency sample sufficiency，並修 VM GPU util semantic capture 後再重跑 validation
- `2026-07-03` 已完成 Normal Baseline v2 collection readiness：
  - 升級 normal-only framework 的 v2 manifest contract，下一輪 run 必填 `campaign_id`、`replicate_id`、`target_offered_rps`、`run_order`、warm-up / measurement / post-observation boundary timestamp、client start/stop、endpoint identity、model/image-set hash、node/GPU UUID、background workload state、telemetry availability 與 sample-age summary
  - normal-only executor 支援 operator-configured `warmup_duration_s`、`measurement_duration_s`、`post_observation_duration_s`，並在 manifest 內寫入正式 measurement window；仍不包含 fan、CoolerControl、cooling intervention 或 Kubernetes control
  - `build_openloop_load_conditioned_dataset.py` 現在會讀取 manifest measurement window，輸出 `manifest_gap_summary.csv`、`latency_target_quality_summary.csv`、`feature_schema_audit.csv`；缺 metadata 的 run 標為 `analysis_ineligible`
  - held-out validation 只使用 `eligible_for_formal_validation=true` 的 rows，並以 debounced anomaly episodes 作正式 false-alarm metric；point-wise exceedance / short-run FA/hour 只保留為 exploratory sensitivity
  - 新增文件與 template：
    - `autoscale-source-split/02-experiment-layer/experiments_yolo/docs/NORMAL_BASELINE_V2_DATA_CONTRACT.md`
    - `autoscale-source-split/02-experiment-layer/experiments_yolo/docs/normal_baseline_v2.preflight_checklist.md`
    - `autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/configs/normal_baseline_v2.operator.template.json`
  - 對既有 9-run v1 normal dataset 執行 v2 readiness audit，確認全部因缺 v2 manifest metadata 被標記 `analysis_ineligible`，不會進入正式 v2 held-out validation
  - 本階段只完成 readiness、dry-run、preflight-only、schema sanity、unit tests 與 synthetic window extraction test；未執行任何 live normal-only run
- `2026-07-03` 已取得第一筆有效 Normal Baseline v2 normal-cooling run：
  - run root: `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_153757/`
  - run dir: `normal_smoke_20260703_153757`
  - 設定為 `0.5 RPS`、`60s warm-up + 300s measurement + 30s post-observation`、`max-inflight 4`
  - request 結果：`195/195` success、`0` drop、`0` timeout/error、safety abort reason 空
  - telemetry：VM rows `386`、nvidia-smi rows `388`、VM sample-age max 約 `1.001s`、GPU max temp `62C`
  - v2 dataset audit: `normal_baseline_v2_dataset_audit/`，共 `390` rows，其中 manifest-defined measurement window `300` rows，formal eligible rows `300`
  - 這是第一筆有效 v2 normal baseline；尚不能做 held-out cross-run validation 或宣稱 normal residual baseline 穩定，下一步需補相同條件 replicate
- `2026-07-03` 已準備 Normal Baseline v2 `r02` / `r03` replicate configs：
  - `autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/configs/normal_baseline_v2_r02.icclz2.draft.json`
  - `autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/configs/normal_baseline_v2_r03.icclz2.draft.json`
  - 兩者皆為 `0.5 RPS`、`60s warm-up + 300s measurement + 30s post-observation`、`max-inflight 4`
  - 兩者 dry-run 與 preflight-only 均通過，無 warnings/errors；live run 需由 operator 在 tmux shell 手動執行
- `2026-07-03` 已取得 Normal Baseline v2 `r02` / `r03`，並完成 r01-r03 combined validation：
  - r02: `dryrun_20260703_172916/normal_smoke_20260703_172916`
  - r03: `dryrun_20260703_173600/normal_smoke_20260703_173600`
  - 三個 v2 runs 均為 `0.5 RPS`，各 `195/195` success、`0` fail/drop/timeout，各有 `300` formal eligible measurement rows
  - telemetry quality：nvidia-smi rows 皆約 `388`，VM rows `386-389`，VM sample-age max 約 `0.70-1.01s`，GPU max temp `61-62C`
  - combined dataset: `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_combined_r01_r03/`
  - held-out validation 已啟用 `Leave-One-Run-Out` 與 `Leave-One-Replicate-Per-Load-Level-Out`，因 manifest replicate_id 完整
  - 結論分類仍為 `insufficient normal replicates` 與 `residual baseline unstable across runs`；主要原因是 r02 rolling latency p50/p95 與 composite risk 有 debounced episodes
  - 因此 Normal Baseline v2 已可分析，但 normal residual threshold 尚未穩定；不應進 cooling-constrained pilot，下一步需檢查 r02 latency shift 或增加更多 v2 normal replicates
- `2026-07-03` 已新增 aggressive fan-cycle availability failure interpretation note：
  - `autoscale-source-split/02-experiment-layer/experiments_yolo/docs/SINGLE_POD_BGCYCLE_AVAILABILITY_FAILURE_NOTE.md`
  - 方法學結論：若 `single_pod_bgload_fan_cycle` 出現大量 `connection refused`、liveness/readiness failure 與 pod restart，該 run 應定位為 availability failure / resilience threshold，而不是乾淨的 thermal-induced latency degradation
  - latency 與 availability 需分開報告；failed requests 不應被當作 latency degradation samples

目前仍未完成的是 external node 的真實 telemetry 恢復：

- `rfsoc4x2-pynq`：inventory 與 aggregator 已接回，但資料源仍失聯
- `openwrt_ap`：inventory 與 aggregator 已接回，但 AP collectors / credentials 尚未恢復

因此目前可視為：

- `01-monitoring-layer` 主線：已完成，可用
- `03-shared-api-dashboard` 的 `Cluster Monitor`：已完成，可用
- API / dashboard user-level service：已完成，可用
- `02-experiment-layer`：已重新驗證到第一段主線
  - `intent-lab` namespace 已建立
  - `nvidia.com/gpu.shared: 4` 已恢復
  - `local/yolo26n:0.1` 已匯入 `icclz1`
  - 三實例 hostPort stack 已 `Running`
  - `2026-06-02` 短版 baseline smoke test 已重新完成
  - `2026-06-02` 短版 `single_pod_serial` 與 `task3` smoke test 已重新完成
  - `2026-06-02` 短版 `fault_fan` 與 `bgload_fan_cycle` smoke test 已重新完成
  - `2026-06-03` `VictoriaMetrics` 已改為 PVC 持久化
  - `2026-06-03` formal thermal / rate-sweep 長時 workflow 已完成縮短版驗證
  - `2026-06-04` Harbor registry workflow 已重建完成到可實際使用：
    - Harbor 已切換為 `HTTPS:8088`
    - `harbor.iccl.local:8088/pre6g/yolo26n:0.1` 已成功 build/tag/push
    - `icclz1` 已成功使用 Harbor image
    - registry 版三實例 `yolo26n-focus/bg-1/bg-2` 已再次回到 `Running`

## Completed

### 1. K3s control-plane

已在目前主機完成：

- `k3s server`
- `write-kubeconfig-mode=0644`
- `node-ip=140.113.179.9`
- `node-external-ip=140.113.179.9`
- `advertise-address=140.113.179.9`
- `tls-san=140.113.179.9`
- `flannel-iface=enp4s0`
- `disable traefik`
- `secrets-encryption=true`

### 2. Core monitoring stack

已部署並驗證：

- `VictoriaMetrics`
- `vmagent` cluster collector
- `vmagent-node-local` DaemonSet
- `node-exporter`
- `kube-state-metrics`
- `Netdata parent`
- `Netdata child`
- `Netdata k8s-state`

對應 manifests：

- [monitoring-rebuild/00-namespaces.yaml](monitoring-rebuild/00-namespaces.yaml)
- [monitoring-rebuild/10-victoria-metrics.yaml](monitoring-rebuild/10-victoria-metrics.yaml)
- [monitoring-rebuild/20-vmagent.yaml](monitoring-rebuild/20-vmagent.yaml)
- [monitoring-rebuild/30-node-exporter.yaml](monitoring-rebuild/30-node-exporter.yaml)
- [monitoring-rebuild/40-kube-state-metrics.yaml](monitoring-rebuild/40-kube-state-metrics.yaml)
- [monitoring-rebuild/55-netdata.yaml](monitoring-rebuild/55-netdata.yaml)
- [monitoring-rebuild/60-netdata-child-stream-config.yaml](monitoring-rebuild/60-netdata-child-stream-config.yaml)

本輪已同步修正：

- `10-victoria-metrics.yaml`
- `20-vmagent.yaml`
- `40-kube-state-metrics.yaml`

把舊的 central-node selector `iccl-cluster-z2` 改成目前 control-plane `icclz2`。

### 3. GPU monitoring and auto-discovery

已部署並驗證：

- `Node Feature Discovery`
- GPU alias rule
- `nvidia-device-plugin`
- `dcgm-exporter`

對應 manifests：

- [monitoring-rebuild/45-nvidia-device-plugin.yaml](monitoring-rebuild/45-nvidia-device-plugin.yaml)
- [monitoring-rebuild/50-dcgm-exporter.yaml](monitoring-rebuild/50-dcgm-exporter.yaml)
- [monitoring-rebuild/70-node-feature-discovery.yaml](monitoring-rebuild/70-node-feature-discovery.yaml)
- [monitoring-rebuild/71-nfd-gpu-alias-rule.yaml](monitoring-rebuild/71-nfd-gpu-alias-rule.yaml)

目前 `icclz1` 已被標成 GPU node，且 GPU metrics 可透過 `dcgm-exporter` 查到。

### 4. API / Dashboard runtime

已建立 host-side runtime：

- Python venv：`/home/icclz2/Pre6G/iccl`
- API env：`autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env`
- host monitoring env：`autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env`
- dashboard env：`autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/.env`

已驗證：

- `autoscale_api` 可啟動
- `GET /api/v1/nodes` 可回資料
- `GET /api/v1/nodes/status` 可回資料
- dashboard `npm run build` 成功
- dashboard 可顯示 `k3s` nodes、`rfsoc4x2-pynq`、`openwrt_ap`
- user-level systemd service 已建立並啟用：
  - `pre6g-autoscale-api.service`
  - `pre6g-cluster-dashboard.service`
- `http://127.0.0.1:8000/` 可回應
- `http://127.0.0.1:4174/` 可回應
- `cluster-dashboard` 已以 Node 22 成功重新 build，包含新 fan-cycle control UI
- `cluster-dashboard` 已新增 `LLM Workloads` table，顯示 workload-centric serving 指標
- `LLM Serving Lab` 現在已明確分成：
  - `Serving Capacity View`
  - `Hardware Capacity View`

### 4.1 LLM workload monitoring notes

目前第一版 `vLLM` workload monitoring 採雙層資料模型：

- node layer:
  - 維持原本 `NodeStatusService`
  - 保留 CPU / RAM / GPU util / VRAM / power / temperature
- workload layer:
  - 新增 `GET /api/v1/workloads`
  - 聚合 `generation TPS` / `prompt TPS` / `waiting requests` / `KV cache`

本輪 live deployment 另外確認：

- single-GPU vLLM Pod 需要 `runtimeClassName: nvidia`
- Gemma 4 cold start 需要 `startupProbe`
- 單 GPU node 更新策略宜用 `Recreate`
- live `autoscale-api` workload query window 已收斂為 `3s`
- `Serving Benchmark` 與 `Offline Throughput Benchmark` 必須分 target：
  - live serving pod 保留給 `vllm bench serve`
  - offline throughput 改走 dedicated benchmark pod

### 5. External node integration status

已完成：

- `collector_nodes.json` 內的 external nodes 可被 inventory 納入 API
- `vm_agg_rfsoc.py` 已改成支援 partial / fallback，不再因單一路徑失敗就整體報錯
- `20-vmagent.yaml` 已補回 `rfsoc4x2-node-exporter` scrape job
- dashboard 對 external nodes 已改成：
  - 缺 telemetry 顯示 `N/A`
  - 外部節點失聯顯示 `OFFLINE`

### 6. Experiment layer partial rebuild

本輪已完成 `02-experiment-layer` 的第一段主線驗證：

- `intent-lab` namespace 已建立
- `icclz1` 再次出現 `nvidia.com/gpu.shared: 4`
- `yolo26n-focus` / `yolo26n-bg-1` / `yolo26n-bg-2` 已成功 rollout
- `http://140.113.179.6:18081/healthz`
- `http://140.113.179.6:18082/healthz`
- `http://140.113.179.6:18083/healthz`
  皆回 `200`
- `scripts/run_A_normal_baseline_yolo.sh` 的短版 smoke test 已於 `2026-06-02` 重新完成：
  - focus `600/600` success，client mean `61.283 ms`，server mean `29.158 ms`
  - bg-1 `300/300` success，client mean `90.206 ms`，server mean `45.408 ms`
  - bg-2 `300/300` success，client mean `90.240 ms`，server mean `45.301 ms`
  - `health_fail_total=0`
  - `warmup_fail_total=0`
  - `clean_normal_candidate=True`
- 本次 baseline 測試輸出已於驗證後刪除，只保留結論
- `single_pod_serial` 短版 smoke test 已於 `2026-06-02` 重新完成：
  - `rows=1423`
  - `success_rate=100%`
  - `client_mean_ms=41.836`
  - `client_p95_ms=46.670`
  - `server_mean_ms=16.570`
- `task3` 短版 service-load smoke test 已於 `2026-06-02` 重新完成：
  - `rows=3118`
  - `success_rate=100%`
  - `client_mean_ms=76.477`
  - `client_p95_ms=121.749`
  - `server_mean_ms=25.342`
  - `server_p95_ms=38.564`
- `single_pod_serial_fault_fan` 短版 smoke test 已於 `2026-06-02` 重新完成：
  - `rows=235`
  - `success_rate=100%`
  - `client_mean_ms=42.322`
  - `client_p95_ms=49.052`
  - `server_mean_ms=16.746`
- `single_pod_bgload_fan_cycle` 短版 smoke test 已於 `2026-06-02` 重新完成：
  - `rows=310`
  - `success_rate=100%`
  - `client_mean_ms=55.685`
  - `client_p95_ms=64.100`
  - `server_mean_ms=31.025`
- worker SSH 已補回：
  - `ssh icclz1-gpu "echo ok"` 可成功
- 本次 `experiments_yolo/results/` 短版測試輸出應於驗證後刪除，只保留結論
- repo-local `iccl` venv 已補齊分析套件：
  - `pandas`
  - `matplotlib`
  - `numpy`
  - `scikit-learn`
  - `joblib`
  - `xgboost`
- Harbor registry workflow 已完成實測：
  - Harbor `pre6g` project 與 push/pull robot account 已建立
  - Harbor host 端 Docker 已配置 insecure registry 僅供 `build/tag/push`
  - Harbor 已從 `HTTP:8088` 收斂為 `HTTPS:8088 + 自簽 CA`
  - `icclz2` 與 `icclz1` 皆已安裝 Harbor CA 並寫入 k3s registry 設定
  - `icclz1` 上 `sudo k3s ctr images pull --user ... harbor.iccl.local:8088/pre6g/yolo26n:0.1` 已成功
  - 配合 `imagePullPolicy: IfNotPresent`，刪除舊 pod 後，registry 版三實例已全部回到 `Running`
- `03-shared-api-dashboard` 的 `Fan-Cycle Experiment` 目前也已與這條 single-pod workflow 對齊：
  - 預設 `focus=yolo26n-focus`
  - 預設 `bg=yolo26n-bg-1`
  - 預設 `TARGET_MODE=pod`

## Current Runtime Snapshot

截至 2026-06-03 確認：

- `kubectl get nodes -o wide` 可見至少：
  - `icclz2` control-plane
  - `icclz1` worker
- `monitoring` namespace 內：
  - `vm-victoria-metrics-single-server` 已就緒
  - central `vmagent` 已就緒
  - `vmagent-node-local` 已就緒
  - `node-exporter` 已就緒
  - `kube-state-metrics` 已就緒
- `gpu-monitoring` namespace 內：
  - `dcgm-exporter` 已在 GPU node 運作
- `netdata` namespace 內：
  - parent / child / k8s-state 已部署

## Validation Results

### Monitoring

已驗證：

- `VictoriaMetrics` 可查到 `up`
- `VictoriaMetrics` 可查到 `node_uname_info`
- GPU node 正常時可查到 `DCGM_FI_DEV_GPU_TEMP`
- `run_vm_aggregator_once.sh icclz2` → `collector_status = ok`
- `run_vm_aggregator_once.sh icclz1` → `collector_status = ok`

### Dashboard / API

已驗證：

- `autoscale_api` 可回應 `GET /`
- `autoscale_api` 可回應 `GET /api/v1/nodes`
- `autoscale_api` 可回應 `GET /api/v1/nodes/status`
- `cluster-dashboard` build 成功
- external nodes 無 telemetry 時不再顯示 `0.0%`
- external nodes 無 telemetry / collector 異常時目前會顯示 `OFFLINE`
- `02-experiment-layer` 三實例 hostPort 目前已恢復：
  - `18081`
  - `18082`
  - `18083`

### Experiment layer formal workflow

已驗證：

- `thermal_analysis/run_cycle_from_master.sh` 已改為使用 repo-local `iccl` venv，短版 direct thermal cycle 可完成
  - run: `thermal_direct_target80_20260603_091045`
  - `aligned_rows=20`
  - `within_band_ratio=0.95`
- `scripts/run_C_thermal_yolo26_3inst_cycles.sh` 已可實際觸發 worker thermal cycle
  - run: `C_thermal_yolo26_3inst_cycle1_20260603_091359`
  - `Thermal command exit code=0`
  - dataset / plots 產生成功
  - `vm_aggregator_merge_after_build.log` 顯示 `vmagg matched ratio = 1.0`
- `scripts/run_yolo26_singlepod_rate_sweep.sh` 短版驗證成功
  - run: `single_yolo26_rate_sweep_20260603_091213`
  - `1 rps` / `3 rps` 皆 `100%` success
- `scripts/run_yolo26_singlepod_async_rate_sweep.sh` 短版驗證成功
  - run: `single_yolo26_async_rate_sweep_20260603_091257`
  - `10 rps` / `20 rps` 皆 `100%` success
- `experiments_yolo/yolo_demo/` 目前僅保留 `README.md`，屬文件型參考目錄，不是可直接執行的 runtime flow

## Current External Node Status

### `rfsoc4x2-pynq`

目前已知狀態：

- `vmagent` 已配置 `rfsoc4x2-node-exporter` scrape job，target 為 `100.91.37.32:9100`
- `vm_agg_rfsoc.py` 已可輸出 `collector_status = ok`
- 但現場資料源仍未恢復：
  - `100.91.37.32:9100` timeout
  - `100.91.37.32:19999` timeout
  - `ssh xilinx@100.91.37.32` timeout
  - Netdata parent 尚未看到 `pynq` mirrored host
  - `~/.ssh/id_ed25519_rfsoc` 不在目前主機上

目前 dashboard 上的狀態解讀：

- inventory 有這台節點
- status 可回傳，但 telemetry 不完整
- 因外部節點 telemetry 缺失，前端目前顯示 `OFFLINE`

### `openwrt_ap`

目前已知狀態：

- inventory 有這台節點
- `vm_agg_ap_gateway.py` 可被 API 納入路徑
- 但現場資料源仍未恢復：
  - 目前主機沒有 `~/.ssh/openwrt_ap_ed25519`
  - 未安裝 / 未驗證 `ap-gateway.service`
  - 未安裝 / 未驗證 `ap-snmp-gateway.service`
  - VictoriaMetrics 內目前沒有 `ap_*` metrics

目前 dashboard 上的狀態解讀：

- inventory 有這台節點
- status 可回傳，但 telemetry 缺失
- 因外部節點 telemetry 缺失，前端目前顯示 `OFFLINE`

## Known Issues

### 1. External node credentials and reachability are missing

這是目前重建最主要未完成項：

- RFSoC SSH key 未恢復
- AP SSH key 未恢復
- RFSoC Netdata / node-exporter 端點不可達
- AP collectors 尚未在此主機重建與驗證

### 2. Long-run experiment results are shortened validations, not full-duration production runs

目前已完成的是正式 workflow 的縮短版驗證：

- thermal direct cycle
- three-instance thermal cycle
- serial rate sweep
- async rate sweep

若之後要做論文或正式報告等級的資料蒐集，仍建議另外重跑完整時長與多 repeat 批次。

## Practical Completion Estimate

以本輪主機實際重建狀態估計：

- `01-monitoring-layer`：約 `95%`
- `03-shared-api-dashboard` 的 `Cluster Monitor`：約 `95%`
- `02-experiment-layer` 主線與常用 formal workflow：約 `90% ~ 95%`
- external nodes 真實 telemetry 恢復：低於 `50%`
- 若先不計 external node 資料源，整體重建完成度約 `90% ~ 95%`

剩餘工作主要是：

- 恢復 RFSoC 可達性與 SSH key
- 恢復 OpenWrt AP credentials / collectors / metrics producer
- 視需求重跑 full-duration / multi-repeat 正式實驗批次
## 2026-07-02 LLM Serving Lab availability fix

- Symptom:
  - `Single Inference` and `Serving Benchmark` in `LLM Serving Lab` were unavailable.
  - `GET /api/v1/workloads` showed `gemma4-e2b-vllm` as `ready_replicas = 0`, `status = not_ready`.
- Root cause:
  - The `iccl-s3-251230` node currently advertises `nvidia.com/gpu.shared: 4` and `nvidia.com/gpu: 0`.
  - The live `ai-serving/gemma4-e2b-vllm` deployment was still requesting `nvidia.com/gpu: 1`.
  - Kubernetes therefore kept the pod in `Pending`, so `autoscale_api` correctly rejected `Single Inference` and `Serving Benchmark` with workload-not-ready behavior.
- Live fix applied:
  - Patched `ai-serving/gemma4-e2b-vllm` to request/limit `nvidia.com/gpu.shared: 1`.
  - Waited for rollout to complete and verified the pod returned to `1/1 Ready` on `iccl-s3-251230`.
- Post-fix verification:
  - `GET /api/v1/workloads` returned `status = ready`, `ready_replicas = 1`.
  - `POST /api/v1/llm-lab/inference` succeeded.
  - `POST /api/v1/llm-lab/benchmarks/runs` with `profile_id = continuous` started successfully.
  - `POST /api/v1/llm-lab/benchmarks/runs/{run_id}/cancel` reached terminal `cancelled` state cleanly.

## 2026-07-02 Open-loop load-conditioned thermal framework

- Added a safe next-stage experiment framework for:
  - `Load Tracking / Load Forecasting`
  - `Load-Conditioned Expected Behavior`
  - `Thermal / Clock / Latency Residual`
  - `Thermal-Performance Degradation Risk`
- Added `open_loop_request_client.py` to generate fixed scheduled arrivals with monotonic timing, bounded in-flight requests, explicit schedule miss / max-in-flight records, raw request logs, and 1s offered-load summaries.
- Hardened `open_loop_request_client.py` to emit separate arrival-binned offered-load summaries and completion-binned realized service activity summaries.
- Added `openloop_campaign_runner.py` with `--dry-run`, `--preflight-only`, and `--normal-only`; cooling-constrained `--run-campaign` now fails closed until that executor exists.
- Added guarded normal-only live smoke and normal-cooling calibration executor paths. They require `--normal-only` and `CONFIRM_NORMAL_SMOKE=YES`, use the open-loop client plus read-only telemetry collectors, and do not perform fan control, CoolerControl, cooling intervention, or Kubernetes scale/restart/delete.
- Added `offline_normal_load_calibration_analysis.py` to summarize candidate offered-load levels without treating completed RPS as offered demand and without auto-selecting final low/medium/high profiles.
- Next research milestone is a single conservative normal-only smoke to validate the data chain. Calibration, replicated normal high-load baselines, residual false-alarm validation, and matched cooling-constrained pilots must follow in that order.
- Added a dedicated normal-only smoke operator template and checklist for Milestone 1. The template keeps safety threshold, endpoint, payload, node, and GPU identity operator-filled and does not enable live execution by itself.
- 2026-07-03 normal-only smoke was executed with normal cooling only:
  - endpoint: `http://10.42.1.46:18080/infer?repeat=10`
  - target offered load: `0.5 RPS`, duration `60s`, max-inflight `4`
  - output root: `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_082457/normal_smoke_20260703_082457`
  - request chain result: `30/30` successful completions, `0` max-inflight drops, `0` timeout completions, `0` abort reason
  - GPU telemetry: `nvidia_smi_rows=59`, max temperature `53C`, SM clock median `1949 MHz`
  - VM telemetry caveat: VM aggregator rows were collected, but max VM sample age reached `116s`; VM-derived features should be reviewed before becoming primary early-warning inputs.
  - No fan control, CoolerControl, cooling intervention, Kubernetes scale/restart/delete, calibration sweep, or long GPU stress was executed.
- Added manifest schema, campaign config example, data contract, execution guide, reproducibility guide, and campaign design doc under `experiments_yolo/docs/`.
- Added load-conditioned residual and event-level onset-only warning scorer for the next open-loop dataset; feature leakage audit requires an actual model manifest or feature-list artifact.
- Current status:
  - Framework and dry-run/preflight path are implemented.
  - No fan control, CoolerControl, Kubernetes scale/restart/delete, or cooling-constrained campaign was executed.
  - The previous closed-loop fan-cycle data remains useful for temporal evidence and method development, but it is not sufficient to claim open-loop unknown-root-cause generalization.

## 2026-07-03 Normal Baseline v2 held-out validation

- Collected first replicated normal-cooling v2 open-loop dataset at `0.5 RPS`:
  - `dryrun_20260703_153757/normal_smoke_20260703_153757` (`r01`)
  - `dryrun_20260703_172916/normal_smoke_20260703_172916` (`r02`)
  - `dryrun_20260703_173600/normal_smoke_20260703_173600` (`r03`)
- Built combined dataset:
  - `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/normal_baseline_v2_combined_r01_r03/`
- Held-out normal residual validation uses run-level folds and manifest replicate identity; no random row split is used.
- Current conclusion:
  - `insufficient normal replicates`
  - `residual baseline unstable across runs`
- r02 shift diagnosis:
  - output: `normal_baseline_v2_combined_r01_r03/replicate_stability_diagnosis/`
  - classification: `normal service baseline shift dominates`
  - rolling latency p50 spread across r01/r02/r03: about `27.75 ms`
  - GPU temperature p50 spread: about `1.0 C`
  - SM clock p50 spread: about `13 MHz`
- Research decision:
  - Normal Baseline v2 is analyzable, but the normal residual threshold is not stable yet.
  - Cooling-constrained pilot remains paused.
  - Next step is to collect more normal-cooling v2 replicates at the same offered RPS, or extend measurement duration and rerun held-out validation.

### Follow-up r04-r06 normal-cooling v2 replicates

- Added configs:
  - `normal_baseline_v2_r04.icclz2.draft.json`
  - `normal_baseline_v2_r05.icclz2.draft.json`
  - `normal_baseline_v2_r06.icclz2.draft.json`
- A sandboxed r04 attempt failed as expected due to local sandbox network/SSH restrictions:
  - `dryrun_20260703_193338/normal_smoke_20260703_193338`
  - abort reason: `missing_gpu_telemetry;error_burst`
  - request errors: `[Errno 1] Operation not permitted`
  - This run is analysis-ineligible and was not included in the combined dataset.
- Valid normal-only live replicates collected with normal cooling only:
  - `dryrun_20260703_194100/normal_smoke_20260703_194100` (`r04`)
  - `dryrun_20260703_194753/normal_smoke_20260703_194753` (`r05`)
  - `dryrun_20260703_195451/normal_smoke_20260703_195451` (`r06`)
- r04-r06 sanity results:
  - each run: `195/195` successful completions, no safety abort
  - VM rows: `386-389`
  - nvidia-smi rows: `388`
  - VM sample-age max: about `0.63-1.01s`
  - GPU max temperature: `62C`
- Rebuilt combined dataset:
  - `normal_baseline_v2_combined_r01_r06/`
  - `6` effective runs, `1800` formal measurement rows
- Held-out validation update:
  - composite risk max debounced episode count decreased to `1`
  - r02 rolling latency p50 shift remains: r02 point exceedance rate `0.7733`, episode `130-359s`
  - r01-r06 rolling latency p50 spread: about `28.90 ms`
  - GPU temperature p50 spread: about `2.0 C`
  - SM clock p50 spread: about `13 MHz`
- Current research decision:
  - Normal-cooling v2 data is now stronger for method development.
  - Latency residual baseline is improved but not fully stable because r02 remains a normal service-state shift.
  - Cooling-constrained pilot remains paused until longer normal runs or run-state normalization is added.

### Service-state normalization and long normal run

- Added offline service-state normalization analyzer:
  - `autoscale-source-split/02-experiment-layer/experiments_yolo/common/offline_service_state_normalized_residual_validation.py`
- Ran sensitivity over r01-r06 held-out validation:
  - `service_state_normalized_validation/` (`60s`)
  - `service_state_normalized_validation_120s/`
  - `service_state_normalized_validation_180s/`
  - `SERVICE_STATE_NORMALIZATION_SENSITIVITY.md`
- Finding:
  - `60s` calibration does not remove r02 rolling latency p50 episode.
  - `120s` and `180s` calibration remove the r02 rolling latency p50 episode.
  - Interpretation: r02 is likely a normal service-state transition/ramp, not thermal degradation evidence.
- Added long normal config:
  - `normal_baseline_v2_long_r07.icclz2.draft.json`
- Executed one normal-only long run:
  - `dryrun_20260703_211041/normal_smoke_20260703_211041`
  - No fan control, CoolerControl, Kubernetes control, cooling-constrained pilot, or GPU stress.
  - `555/555` successful completions.
  - VM rows: `1107`; nvidia-smi rows: `1106`; VM sample-age max about `1.00s`; GPU max temp `62C`.
  - Formal measurement: `900s` after `180s` warm-up.
- Long r07 audit:
  - `normal_baseline_v2_long_r07_analysis/LONG_R07_RUNSTATE_STABILITY_AUDIT.md`
  - rolling latency p50 first-to-last third delta: about `-4.46 ms`
  - rolling latency p95 first-to-last third delta: about `+0.66 ms`
  - GPU temp / SM clock median first-to-last third delta: no material drift
- Current decision:
  - Long normal-cooling protocol looks more appropriate for stable latency residual baselines.
  - One long run is not enough; collect at least two more long normal-cooling replicates before cooling-constrained pilot.

### Long normal r08-r09 completion and long-baseline validation

- Added configs:
  - `normal_baseline_v2_long_r08.icclz2.draft.json`
  - `normal_baseline_v2_long_r09.icclz2.draft.json`
- Executed normal-only long runs:
  - `dryrun_20260703_214750/normal_smoke_20260703_214750` (`r08_long`)
  - `dryrun_20260703_220649/normal_smoke_20260703_220649` (`r09_long`)
- Safety/data quality:
  - r08/r09 each: `555/555` successful completions, no safety abort
  - VM rows: `1109`
  - nvidia-smi rows: `1106-1107`
  - VM sample-age max: about `0.96-1.00s`
  - GPU max temperature: `62-63C`
- Built combined long baseline:
  - `normal_baseline_v2_long_r07_r09_analysis/`
  - `3` long runs, `2700` formal measurement rows
- Long-run stability:
  - r07/r08/r09 GPU temp median first-to-last third delta: `0C`
  - r07/r08/r09 SM clock median first-to-last third delta: `0 MHz`
  - after-120s latency p50 levels still differ across runs: about `185.5-202.4 ms`
- Held-out raw latency residual:
  - still unstable across runs because r08 has a higher normal latency level than r07/r09
  - this is interpreted as service baseline level shift, not thermal degradation evidence
- 180s run-local healthy calibration:
  - rolling_latency_p50 episodes: `0`
  - rolling_latency_p95 episodes: `0`
  - composite risk retains small non-latency episodes
- Current research decision:
  - Long normal protocol is usable as a stronger baseline.
  - Future matched cooling-constrained pilot should include the same long warm-up and a pre-registered run-local healthy calibration window.
  - Raw cross-run latency residual without calibration should not be the primary warning signal.

### Matched pilot readiness contract

- Added pilot contract:
  - `autoscale-source-split/02-experiment-layer/experiments_yolo/docs/MATCHED_COOLING_CONSTRAINED_PILOT_CONTRACT.md`
- Added offline readiness audit:
  - `autoscale-source-split/02-experiment-layer/experiments_yolo/common/offline_matched_pilot_readiness_audit.py`
- Audit output:
  - `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/matched_pilot_readiness_audit/`
- Decision:
  - `method_ready_but_live_cooling_executor_still_fail_closed`
- Interpretation:
  - The normal long baseline is method-ready for matched pilot design.
  - Any pilot must use `180s` healthy calibration, `900s` measurement, and the same offered load / endpoint / payload / model / GPU identity.
  - The live cooling-constrained executor is still intentionally not implemented; `--run-campaign` remains fail-closed.
