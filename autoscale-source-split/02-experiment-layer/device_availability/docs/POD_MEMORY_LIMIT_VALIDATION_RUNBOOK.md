# Pod Memory Limit Validation Runbook

Status: `validated once on protected sentinel baseline`

## Objective

驗證導入 stress Pod `memory limit` 後，memory pressure 失敗是否會被侷限在 workload Pod，而不擴散成：

- `Node NotReady`
- `k3s-agent` restart
- `containerd` restart
- sentinel confirmed outage

## Hypothesis

在 stress Pod 設定明確 `requests / limits` 後：

- workload failure 可表現為 `OOMKilled` 或 `Evicted`
- 但不應升級成 node-level failure

## Suggested Profiles

`MEM-contained`

- 目的：接近但不超過 Pod limit
- 預期：不 OOM、不 eviction

`MEM-boundary`

- 目的：接近 node memory pressure 邊界
- 預期：可能 OOM / eviction，但 Node 仍維持正常

## Prepared Overlay

Overlay:

- `manifests/overlays/pod-memory-limit`

目前 prepared patch 為：

- CPU stress:
  - requests: `cpu=500m`, `memory=64Mi`
  - limits: `cpu=4`, `memory=128Mi`
- MEM stress:
  - requests: `cpu=250m`, `memory=256Mi`
  - limits: `cpu=1`, `memory=7Gi`
  - `backoffLimit: 0`

## Important Note

目前長版 / 短版 phase 主要由 `stress_runner.sh` 動態建立 stress jobs。

因此：

1. 這個 overlay 主要作為靜態 manifest 參考與保留
2. 實際 live phase run 應同步帶入對應的 `STRESS_*` 環境變數

## Suggested Short Validation

```text
BASELINE       10 min
MEM-contained  20 min
RECOVERY       10 min
MEM-boundary   20 min
FINAL          10 min
Total          70 min
```

Validated run reference:

- `r1_pod_memory_limit_20260708_protected`
- live execution used dynamic stress jobs from `stress_runner.sh`
- key memory settings:
  - `MEM_STRESS_REQUEST_CPU=250m`
  - `MEM_STRESS_LIMIT_CPU=1`
  - `MEM_STRESS_REQUEST_MEMORY=256Mi`
  - `MEM_STRESS_LIMIT_MEMORY=7Gi`
  - `MEM_CONTAINED_BYTES=6G`
  - `MEM_BOUNDARY_BYTES=7G`

## Pass Criteria

1. `confirmed_outage_events = 0`
2. `Node Ready interruption = 0`
3. sentinel restart / OOM = `0`
4. host OOM = `0`
5. `k3s-agent / containerd` restart = `0`
6. stress Pod `OOMKilled / Evicted` 可接受，但需記錄為 workload containment event

## Latest Validation Outcome

1. `MEM-contained` 與 `MEM-boundary` phase 都未觀察到 confirmed outage。
2. `MEM-boundary` 期間觀察到 workload-level `OOMKilled`，但 `Node Ready` 與 sentinel probe 維持正常。
3. 後續進 `R2 evictionHard` 前，可沿用相同 probe 定義與 phase 長度。
