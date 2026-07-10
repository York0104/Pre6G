# Node-Level Protection Plan

Status: `R0 completed, R1 completed, R2-R4 planned`

## Objective

在既有 `P2 Pod-level protected baseline` 之後，逐步驗證：

1. stress Pod 的 memory pressure 是否能被侷限在 Pod cgroup 內
2. kubelet `evictionHard` 是否能保住 Node 管理能力
3. `systemReserved / kubeReserved` 是否能進一步保護 OS / K3s 元件

## Recommended Order

1. `R0`: seal `Phase 2 protected baseline` - completed
2. `R1`: pod memory limit - completed
3. `R2`: short `evictionHard` validation - next
4. `R3`: `evictionHard` `6h` validation
5. `R4`: `systemReserved / kubeReserved` evaluation

## Scope Boundary

Node-level protection 實驗中，不應同時改：

- confirmed outage 規則
- compute-check 設計
- probe timeout
- stress phase 長度
- stress 強度
- sentinel image

## Current Prepared Assets

- `docs/PHASE2_PROTECTED_BASELINE_SUMMARY_20260708.md`
- `docs/POD_MEMORY_LIMIT_VALIDATION_RUNBOOK.md`
- `docs/EVICTIONHARD_VALIDATION_RUNBOOK.md`
- `manifests/overlays/pod-memory-limit/`
- `manifests/node-protection/`
- `results/NODE_LEVEL_PROTECTION_R0_R1_20260708.md`
- `results/NODE_LEVEL_PROTECTION_R2_EVICTIONHARD_20260708.md`
- `run_r2_evictionhard_short_validation.sh`

## Current State

1. `R0` 已將 `phase2_formal_20260708_protected` 封存為 `P2 Pod-level protected baseline`。
2. `R1` 已完成一次 live validation：`r1_pod_memory_limit_20260708_protected`。
3. `R2` 的 runbook、example config、report template 與 runner 已建立，但尚未套用到 live node。
4. 目前最合理的下一步是完成 `R2` preflight、核可 `evictionHard` 套用與 short validation，而不是直接跳 `systemReserved / kubeReserved`。

## Important Note

`evictionHard`、`systemReserved`、`kubeReserved` 通常屬於 K3s agent / kubelet config。

因此：

- 應以 runbook、example config、rollback guide 方式管理
- 不應假設可僅用 `kubectl apply -k` 完成
