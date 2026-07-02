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
