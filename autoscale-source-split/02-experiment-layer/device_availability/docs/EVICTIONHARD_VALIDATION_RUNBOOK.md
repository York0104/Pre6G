# evictionHard Validation Runbook

Status: `prepared, not yet applied`

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
