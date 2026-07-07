# Device-Service Availability Experiment

本文件定義目前 `Pre6G` 現場環境下，針對單一運算節點的設備服務可用性驗證架構。

目標不是驗證整體 AI inference service，也不是驗證機房等級的硬體高可用，而是驗證：

- 在受控 CPU / RAM 壓力下，目標 Worker 是否仍可被監控
- 是否仍可被探測
- 是否仍可被管理
- `k3s-agent`、節點代理與監控鏈路是否持續存活

目前設計基準節點：

- Observer / control-plane: `icclz2` (`140.113.179.9`)
- Target worker: `icclz1` (`140.113.179.6`)

## 1. Design Scope

本實驗的 availability scope 限定為單節點設備服務能力：

- Kubernetes `Node Ready`
- node-local sentinel health
- 基本 compute check 可完成

不納入本輪 formal claim 的範圍：

- 斷電
- 實體 NIC / switch 故障
- 主機板或儲存裝置硬體故障
- 多節點故障轉移
- inference latency / success rate 本身
- GPU thermal / fan-control 特定行為

因此這份設計適合作為：

- `device-service availability >= 99.9%` 的初步驗證
- 後續擴充到 GPU / thermal / workload stress 前的基線版本

## 2. Current Environment Basis

本設計直接依附目前 repo 與現場已存在的元件，不另外假設新平台：

- `icclz1` 已為現行可用 GPU worker
- `icclz1` 已有 `node-exporter`、`vmagent-node-local`、`Netdata child`
- `icclz2` 已可提供 `VictoriaMetrics`、`Netdata parent`、`autoscale_api`
- `k3s` control-plane 與既有 monitoring layer 已完成主線重建

可依附的 repo 入口：

- `01-monitoring-layer/`
- `02-experiment-layer/`
- `03-shared-api-dashboard/`

## 3. Architecture

### 3.1 Logical Topology

```text
Observer / Control Plane: icclz2 (140.113.179.9)
├─ K3s control-plane
├─ VictoriaMetrics
├─ Netdata parent
├─ autoscale_api (:8000)
├─ availability_probe.py
├─ stress_runner.sh
└─ results/<run_id>/
   ├─ availability.csv
   ├─ node_status.log
   ├─ k8s_events.log
   └─ summary.json

Target Worker: icclz1 (140.113.179.6)
├─ k3s-agent
├─ kubelet
├─ node-exporter
├─ vmagent-node-local
├─ Netdata child
├─ node-sentinel
├─ cpu-stress Job
└─ mem-stress Job
```

### 3.2 Data Flow

```text
stress_runner.sh
  -> create / delete CPU and memory stress Jobs on icclz1

availability_probe.py
  -> query Kubernetes Node Ready state
  -> call http://icclz1:18080/healthz
  -> call http://icclz1:18080/compute-check
  -> verify metrics endpoint reachability
  -> write availability.csv

summary step
  -> aggregate DOWN intervals
  -> compute availability ratio
  -> export summary.json
```

## 4. Component Responsibilities

### 4.1 `node-sentinel`

部署在 target worker 的輕量節點代理服務。

責任：

- 提供 `GET /healthz`
- 提供 `GET /compute-check`
- 提供 `GET /status`
- 回報節點最基本的存活與可管理能力

設計要求：

- 固定部署於 `icclz1`
- 不經一般 `Service` load balancing
- 使用 `hostNetwork: true`
- 使用 `nodeSelector` 或等價方式固定到 target node
- 低資源占用
- 明確且固定的 resource requests / limits
- 建議以 `ConfigMap` 掛載 `node_sentinel.py`，避免依賴 target node 上的 repo 路徑

### 4.2 `availability_probe.py`

從 `icclz2` 執行的外部觀測者。

責任：

- 每 5 秒檢查一次 target worker
- 記錄 `Node Ready`
- 記錄 sentinel 回應狀態
- 記錄 compute-check latency
- 額外記錄 metrics endpoint reachability
- 在任何核心條件失敗時標記 `DOWN`

為何放在 `icclz2`：

- 避免 observer 與受測節點共命運
- 若 `icclz1` 壓力過大或失聯，仍能從外部保留完整觀測

### 4.3 `stress_runner.sh`

受控壓力注入器。

責任：

- 啟動 `CPU-M`、`MEM-M`、`MIX-H` 等 phase
- 控制壓力開始與結束時間
- 產出 phase metadata
- 配合 probe 一起標記目前 phase

### 4.4 Monitoring Backends

本實驗第一版只把現有 monitoring backend 當作「旁證資料來源」，不重新定義其功能。

使用角色：

- `VictoriaMetrics`: 保留後續延伸查詢與事後比對
- `Netdata parent / child`: 提供事後觀測與對照資料
- `node-exporter`: 提供另一條 node-level 旁證資料

### 4.5 `autoscale_api`

第一版不是必要依賴，但建議作為後續整合入口。

可用角色：

- 讀 node inventory / status
- 後續整合 availability run metadata
- 提供 dashboard 顯示實驗歷程

## 5. Probe Contract

### 5.1 Required Endpoints

`node-sentinel` 至少提供：

- `GET /healthz`
- `GET /compute-check`
- `GET /status`

### 5.2 Endpoint Semantics

`/healthz`

- HTTP `200`
- 代表 sentinel process 仍在
- 不代表整體節點性能正常

`/compute-check`

- HTTP `200`
- 執行固定、小型、低成本計算
- 回傳計算耗時
- 用來確認節點仍保有最基本 compute capacity

`/status`

- 回傳 hostname
- 回傳 timestamp
- 回傳 CPU load
- 回傳 `MemAvailable`
- 主要供除錯與人工判讀

### 5.3 Metrics Reachability

metrics endpoint 在 MVP 階段不納入核心 availability 條件，只保留為 observation field：

- `node-exporter`
- `Netdata`

建議第一版以現場較穩定者作為 primary observation source，另一條作為 debug 證據。

## 6. State Classification

### 6.1 `UP`

同時滿足：

- `Node Ready=True`
- `/healthz` HTTP `200`
- `/compute-check` HTTP `200`
- `/compute-check latency < 2s`

### 6.2 `DEGRADED`

核心探測仍成功，但存在輕度退化跡象，例如：

- `/compute-check latency` 高於 baseline 但仍小於 2 秒
- PSI 或 load 明顯升高
- metrics freshness 邊緣化，但尚未中斷

`DEGRADED` 仍計入 availability，但需另外統計。

### 6.3 `DOWN`

任一核心條件失敗即記為 `DOWN`：

- `Node Ready=False`
- `/healthz` timeout / non-200
- `/compute-check` timeout / non-200
- `/compute-check latency >= 2s`

### 6.4 Downtime Reason

建議至少分類：

- `node_not_ready`
- `sentinel_unreachable`
- `compute_check_failed`
- `compute_check_timeout`
- `unknown`

補充：

- `metrics_unreachable` 在 MVP 階段只作為 observation flag，不直接算入 `DOWN`

## 7. Availability Formula

正式計算：

```text
A_device = (T_obs - T_down) / T_obs * 100%
```

### 7.1 6-Hour Quick Validation

- `T_obs = 21600s`
- 若目標 `A_device >= 99.9%`
- 則 `T_down <= 21.6s`

### 7.2 24-Hour Formal Validation

- `T_obs = 86400s`
- 若目標 `A_device >= 99.9%`
- 則 `T_down <= 86.4s`

## 8. 6-Hour Validation Plan

### 8.1 Recommended Schedule

```text
00:00-00:30  BASELINE         no stress
00:30-01:30  CPU-M            CPU 60-65%
01:30-02:00  RECOVERY-1       no stress
02:00-03:00  MEM-M            RAM 55-60%
03:00-03:30  RECOVERY-2       no stress
03:30-05:00  MIX-H            CPU 70% + RAM 65%
05:00-06:00  FINAL-RECOVERY   no stress
```

### 8.2 Why This Sequence

- 先建立 baseline latency / probe 成功率
- 單獨拆 CPU 與 memory 壓力，便於定位 failure mode
- 最後再做混合壓力
- recovery phase 可辨識 residual pressure 與延遲恢復問題

## 9. Resource Isolation Principles

這部分比 probe 本身更關鍵。

### 9.1 Do Not Saturate The Whole Node

第一輪不要把 `icclz1` 打到滿載。

建議：

- CPU 壓力先控制在 `60-80%`
- RAM 壓力先控制在 `55-70%`
- 保留 system / kubelet / k3s-agent / sentinel 生存空間

### 9.2 Protect Control Components

需保護的元件：

- `k3s-agent`
- `kubelet`
- `node-sentinel`
- `node-exporter`
- `Netdata child`

建議：

- sentinel 使用明確 `requests`
- sentinel 使用較高優先權
- stress Jobs 避免拿走所有 allocatable resource

### 9.3 Keep Compute Check Small

`/compute-check` 的負載必須：

- 固定
- 短小
- deterministic

避免 probe 自己變成壓力來源。

## 10. Output Artifacts

每次 run 建議保存：

- `availability.csv`
- `phase_timeline.json`
- `summary.json`
- `node_status.log`
- `k8s_events.log`
- `probe.log`

### 10.1 `availability.csv`

建議欄位：

```text
timestamp,phase,node,ready,healthz_ok,compute_ok,metrics_ok,healthz_ms,compute_ms,state,downtime_reason
```

其中：

- `metrics_ok` 在 MVP 階段僅作為旁證欄位
- `state` 只由 `ready`、`healthz_ok`、`compute_ok`、`compute_ms` 決定

### 10.2 `summary.json`

建議欄位：

- `run_id`
- `target_node`
- `sampling_interval_seconds`
- `total_observation_seconds`
- `total_down_seconds`
- `availability_percent`
- `downtime_reason_breakdown`
- `phase_summary`

## 11. Repo Layout Proposal

建議本實驗固定放在：

```text
02-experiment-layer/device_availability/
├─ README.md
├─ availability_probe.py
├─ stress_runner.sh
├─ manifests/
│  ├─ node-sentinel-daemonset.yaml
│  ├─ cpu-stress-job.yaml
│  └─ mem-stress-job.yaml
└─ results/
```

目前這份文件先作為該目錄的架構基準。

目前實作追蹤請看：

- `IMPLEMENTATION_PROGRESS.md`

## 12. Implementation Order

建議實作順序：

1. `node-sentinel` 最小版
2. `node-sentinel` `DaemonSet` manifest
3. `availability_probe.py`
4. `stress_runner.sh`
5. `6-hour` operator runbook
6. `summary` 聚合腳本

## 13. Success Criteria

第一輪成功標準：

- `icclz1` 在完整 6 小時流程中未出現長時間 `DOWN`
- 總 downtime 小於 `21.6s`
- `Node Ready` 與 sentinel probe 記錄完整
- metrics 鏈路在壓力下仍具可達性

若第一輪通過，再進入：

- 24 小時正式版
- 加入更嚴格 `DEGRADED` 定義
- 評估是否納入 GPU / thermal stress 作為第二階段擴充

## 14. Explicit Non-Goals

為避免設計膨脹，第一版先不做：

- 多 worker 並行驗證
- Pod 自動修復時間最佳化
- dashboard 視覺化
- 熱控 / GPU 負載聯動
- 跨節點 failover
- formal SLA 對外承諾文件

第一版的成功關鍵是先把單節點 device-service availability 的觀測鏈做乾淨、做穩、做可重複。
