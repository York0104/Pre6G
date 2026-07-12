# evictionHard Validation Runbook

Status: `evictionHard applied on icclz1; R2f/R2g safety evidence completed, R2h progressive-ramp retry pending`

## Objective

驗證在既有 protected sentinel 與 stress-low workload 條件下，新增 kubelet `evictionHard` 後：

1. 多個低優先權 memory stress Pod 是否會在 node-level memory pressure 下被優先處理
2. `Node Ready`、`k3s-agent`、`containerd`、`node-sentinel` 是否可維持正常
3. `Evicted` 與 `MemoryPressure` 是否能作為 `evictionHard` 介入的主要證據

## Scope

R2 固定保留：

- sentinel `Guaranteed QoS`
- sentinel high `PriorityClass`
- stress low `PriorityClass`
- stress pod memory limits
- confirmed outage rule
- background-worker `node-sentinel`

R2 新增的唯一 node-level protection：

- `evictionHard`

暫時不要一起改：

- `systemReserved`
- `kubeReserved`
- `enforceNodeAllocatable`
- `systemd-oomd`
- `user.slice CPUWeight`

## Recommended kubelet Setting

第一版建議值：

```yaml
kubelet-arg:
  - "eviction-hard=memory.available<2Gi,nodefs.available<10%,imagefs.available<15%"
```

若現場記憶體較小，可下修為：

```yaml
kubelet-arg:
  - "eviction-hard=memory.available<1Gi,nodefs.available<10%,imagefs.available<15%"
```

## Key Design Rule

R2 不能只用單一高記憶體 stress pod。

若只有：

- 單 pod `limit`
- 單 pod `vm-bytes`

則結果很容易先退化成：

- pod cgroup `OOMKilled`

而不是：

- kubelet node-pressure eviction

因此 R2 應改用：

- 多個 low-priority memory stress pod 並行
- 單 pod `vm-bytes < memory limit`
- aggregate memory demand 逼近 `memory.available` threshold

## R2 Launch Reliability Gate

正式 phase 前必須先通過下列 gate，否則該次執行不計為 R2：

1. 以相同 image 在目標 node 完成 prewarm Job。
2. 所有 R2 stress container 明確指定 `imagePullPolicy: IfNotPresent`，避免 `:latest` 隱含的 `Always` policy 在大量並行 Pod 啟動時再次查詢 registry。
3. 用同 image、priority、resources 與 parallelism 的非壓力 `sleep` Job 啟動 launch gate；在 180 秒內至少 90% Pod 必須進入 `Running`，且不得出現 `ErrImagePull` 或 `ImagePullBackOff`。Gate 本身不執行 memory stress。
4. `device-availability-stress-nonpreempting-low` 必須為 `value: -1000`、`preemptionPolicy: Never`。R2 的 stress workload 必須能在 node pressure 下被 kubelet 優先 eviction，但不得為了排程而主動 preempt 既有非實驗 workload。

Runner 會把 gate 結果寫入：

- `launch_gate_summary.env`
- `launch_gate_pods.log`
- gate 失敗時的 `launch_gate_job_describe.log` 與 `launch_gate_events.log`

目前已知失敗原因是 registry `pull QPS exceeded`，不是 image reference 不存在。未通過 gate 時應先處理 image pull，不應把 availability 結果解讀成 evictionHard 成功。

`r2d_evictionhard_short_20260711_protected` 已確認 prewarm 與 23 個 gate Pod 均成功啟動；runner 的 JSONPath 計數誤判為 0，且事件顯示舊 `device-availability-stress-low`（value `1000`）曾 preempt `yolo26n-bg`。因此此輪不計為 R2；後續必須先套用新的 negative-priority non-preempting stress class。R2 runner 的 CPU request 也固定為每 Pod `10m`，避免啟動 gate 因 scheduler CPU request 而排不滿。

`r2e_evictionhard_short_20260711_protected` 已通過 prewarm 與新 launch gate，但 profile 計算前仍殘留 43 個舊 R2 stress Pod，導致 baseline `MemAvailable` 僅約 3.3Gi、正式 profile 退化為 2–3 Pod。此輪僅能作為 cleanup 缺口的診斷證據，不計為有效 R2。Runner 現在會先刪除並等待所有既有 R2 Job/Pod 消失、等待記憶體回穩後才推導 profile。

每次正式執行必須使用新的 `RUN_ID` / `OUT_DIR`。Runner 會拒絕寫入已含 `availability.csv` 或 `summary.json` 的結果目錄；分析器也會以 `summary.json` 的 observation window 排除意外混入的舊 CSV 列。

## R2f Result And R2g Adjustment

`r2f_evictionhard_short_20260711_protected` 是第一輪通過 clean-baseline、prewarm 與 21/23 launch gate 的完整 100-minute profile。它記錄了：

- `confirmed_outage_events=0`、`samples_down=0`
- `Node Ready=True`，且未見 `MemoryPressure`、`Evicted` 或 image pull failure
- 3 個 distinct stress Pod `OOMKilled`

這支持設備服務在本輪壓力下仍可達，但因 `3Gi` cgroup limit 先觸發，不能作為 evictionHard 已介入的證據。

R2g 是唯一調整：

- `PER_POD_LIMIT_MEMORY=4Gi`
- 保持 `PER_POD_VM_MIB=2600`、`MEM_AGG_H_VM_MIB=2856`、parallelism、phase durations、probe rule、priority class 與 kubelet evictionHard 不變

`4Gi` limit 為每個 `2856M` high-profile workload 留出 cgroup headroom，目標是讓 aggregate demand 先觸發 node-level pressure，而非個別 container 的 memory limit。R2g 仍必須滿足既有 host safety criteria；若發生 Host OOM、Node NotReady、Sentinel/K3s agent/containerd 異常，立即視為失敗，不再提高壓力。

R2g 已確認 `4Gi` manifest 確實套用，但仍有 4 個 distinct stress Pod `OOMKilled`，且 Job 在約十秒內因 `backoffLimit=0` 停止其餘 Pod；未見 `MemoryPressure` 或 `Evicted`。這表示 23 Pod 同時分配形成過快的壓力尖峰。R2h 不增加單 Pod memory、總目標 parallelism 或測試時間，而是將 `MEM-AGG-H` 由 4 Pod 起始、每 15 秒增加 4 Pod，直到 23 Pod，讓 kubelet 有觀察及 node-pressure eviction 的時間。

## Measurement Caveat

node-exporter 的 `MemAvailable` 僅用於推導 aggregate 壓力 profile；它不是 kubelet 的 eviction signal。Kubelet 使用 cgroupfs working set 計算 `memory.available`，因此 runner 會額外保存 kubelet `/stats/summary` 的 before/after snapshot，並仍以 `MemoryPressure`、`Evicted` event 與 node condition 作為 R2 成立證據。

## Suggested 100-minute Profile

```text
BASELINE        10 min
MEM-AGG-M       20 min
RECOVERY-1      10 min
MEM-AGG-H       25 min
RECOVERY-2      10 min
MIX-AGG-M       15 min
FINAL-RECOVERY  10 min
Total          100 min
```

Interpretation:

1. `MEM-AGG-M`
   - 主要確認 aggregation 能造成壓力但不一定觸發 eviction
2. `MEM-AGG-H`
   - 主要驗證 `Evicted` 或 `MemoryPressure=True` 是否出現
3. `MIX-AGG-M`
   - 觀察 CPU contention 與 aggregate memory pressure 疊加後，管理面是否仍穩定

## Core Evidence

R2 報告至少要包含：

1. `Node Ready`
2. `Node MemoryPressure`
3. `Evicted` stress-low pod list
4. `OOMKilled` stress pod list
5. sentinel restart / OOM / eviction status
6. `k3s-agent` restart / `containerd` restart
7. host OOM evidence

## Pass Criteria

必須全部滿足：

1. `confirmed_outage_events = 0`
2. `samples_down = 0`
3. `Node Ready interruption = 0`
4. sentinel restart / OOM / eviction = `0`
5. `k3s-agent` restart = `0`
6. `containerd` restart = `0`
7. `Host OOM = 0`

並且至少滿足以下其一：

1. 觀察到 `Evicted` stress-low pod
2. 觀察到 `MemoryPressure=True`，但 node / sentinel / `k3s-agent` 全程正常

若只有：

- `OOMKilled`
- `MemoryPressure=False`
- `Evicted=0`

則應判定為：

- `R2 attempt fell back to R1-style pod-level containment`

## Runner Assets

Primary runner:

- `run_r2_evictionhard_short_validation.sh`

Generated artifacts:

- `results/<run_id>/generated/r2-mem-agg-m.yaml`
- `results/<run_id>/generated/r2-mem-agg-h.yaml`
- `results/<run_id>/generated/r2-mix-agg-m.yaml`
- `results/<run_id>/generated/r2-eviction-hard-config.yaml`

Template report:

- `results/NODE_LEVEL_PROTECTION_R2_EVICTIONHARD_20260708.md`

## Tuned Preflight Reference

Latest tuned preflight:

- `results/r2_evictionhard_preflight_20260708_tuned/`

Current tuned profile:

- `pressure_profile_status=target_reachable`
- `MEM_AGG_H_PARALLELISM=22`
- `MEM_AGG_H_VM_MIB=2600`
- `MIX_AGG_M_PARALLELISM=21`

Interpretation:

- 這組 tuned profile 已不再是「過度保守壓不到 eviction 線」的狀態
- 後續正式 `R2` 可直接以這個 preflight 結果作為 apply 前基線

## Operator Steps

### Option A: Directly on `icclz1`

若你可以直接登入 `icclz1`，這是最穩定的做法。

1. 備份 K3s config

```bash
sudo mkdir -p /etc/rancher/k3s/backup-device-availability
sudo cp -a /etc/rancher/k3s/config.yaml \
  /etc/rancher/k3s/backup-device-availability/config.yaml.$(date +%Y%m%d_%H%M%S) \
  2>/dev/null || true
```

2. 將以下內容合併到 `/etc/rancher/k3s/config.yaml`

```yaml
kubelet-arg:
  - "eviction-hard=memory.available<2Gi,nodefs.available<10%,imagefs.available<15%"
```

若原本已經有 `kubelet-arg:`，要合併，不要覆蓋既有值。

3. 重啟 agent

```bash
sudo systemctl restart k3s-agent
```

4. 回到 `icclz2` 驗證 node 恢復

```bash
kubectl wait node/icclz1 --for=condition=Ready --timeout=180s
kubectl get node icclz1 -o wide
kubectl -n intent-lab get pods -o wide
```

若 `Node Ready` 無法恢復，不要進 stress validation，先 rollback。

### Option B: From `icclz2` via SSH

若 `icclz2 -> icclz1` 的 SSH 已打通，可直接用 tuned preflight 產出的 helper：

- `results/r2_evictionhard_preflight_20260708_tuned/generated/apply_eviction_hard.sh`
- `results/r2_evictionhard_preflight_20260708_tuned/generated/rollback_eviction_hard.sh`

目前 helper 只負責備份與提示，不會自動 merge live config；這是刻意保守的設計。

## Rollback

若套用後 node 無法正常回 `Ready`，在 `icclz1` 上：

1. 還原上一份 `/etc/rancher/k3s/config.yaml`
2. 執行：

```bash
sudo systemctl restart k3s-agent
```

3. 再由 `icclz2` 檢查：

```bash
kubectl wait node/icclz1 --for=condition=Ready --timeout=180s
```

## SSH Note

目前我這個執行環境對 `ssh icclz1` 會收到：

- `Permission denied (publickey,password)`

這通常代表：

1. `icclz2` 到 `icclz1` 的 SSH 金鑰尚未配置
2. 或 `icclz1` 不接受目前這個帳號 / 金鑰

這不是 Kubernetes 或本實驗本身的錯，也不是「本來就一定不該有權限」。

對實驗而言：

1. 若你本來就打算人工登入 `icclz1` 做 node-level config，現在不修 SSH 也可以繼續
2. 若你希望後續 `R2/R3/R4` 都能從 `icclz2` 半自動操作，建議補通 `icclz2 -> icclz1` 的 SSH key-based access

最小需要你處理的事只有一件：

- 確認你是否能直接登入 `icclz1`

如果可以，下一步不用先修 SSH；直接照 `Option A` 操作即可。
如果不行，而且你想讓我後續從這裡代跑 node-level apply / rollback / journal 收集，就需要你先把 `icclz2` 到 `icclz1` 的 SSH 權限打通。

## Execution Note

目前 runner 已可：

1. 收集 preflight
2. 計算 aggregate pressure profile
3. 產生 generated manifests
4. 輸出報告骨架與結果目錄

是否真的套用 kubelet config 與重啟 `k3s-agent`，仍應在明確核可後執行。
