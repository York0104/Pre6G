# Pod-Level Protection Plan

Status: `prepared, not applied`

這份文件只描述 pod-level protection 實驗資產的準備狀態，不代表目前 live cluster 已套用。

## Goal

為未來的 protection A/B 實驗預先準備：

1. Sentinel `Guaranteed QoS`
2. Sentinel high `PriorityClass`
3. Stress job low `PriorityClass`
4. resource requests / limits
5. clear rollback path

## Scope Boundary

這份 plan 刻意不混入目前的量測鏈穩定化工作線。

也就是說：

- `node-sentinel / probe` 的穩定化仍屬於工作線 A
- pod-level protection 只先做 manifest / runbook / checklist 準備

## Prepared Assets

Prepared manifests:

- `manifests/base/kustomization.yaml`
- `manifests/base/node-sentinel-daemonset.yaml`
- `manifests/stress-jobs/kustomization.yaml`
- `manifests/stress-jobs/cpu-stress-job.yaml`
- `manifests/stress-jobs/mem-stress-job.yaml`
- `manifests/overlays/pod-protection/kustomization.yaml`
- `manifests/overlays/pod-protection/priorityclasses.yaml`
- `manifests/overlays/pod-protection/sentinel-qos-priority-patch.yaml`
- `manifests/overlays/pod-protection/stress-low-priority-patch.yaml`

## Design Notes

Sentinel patch:

- adds `device-availability-sentinel-high`
- sets requests = limits for CPU / memory
- current prepared value: `cpu=250m`, `memory=128Mi`

Stress patch:

- adds `device-availability-stress-nonpreempting-low`
- sets explicit requests / limits for CPU and MEM jobs
- `MIX` phase will inherit the same lower-priority behavior because it reuses CPU and MEM jobs together
- 長版 phase 的 stress job 由 `stress_runner.sh` 動態建立，因此 Case B 也要帶入對應的 `STRESS_*` 環境變數

## Rollback Principle

Rollback 不維護獨立複製 manifest。

準則是：

- protection enable: `kubectl apply -k manifests/overlays/pod-protection`
- rollback to base: `kubectl apply -k manifests/base`
- `manifests/base` 現在只回復 sentinel baseline，不會順手建立 stress jobs

## Not For Immediate Use

在目前階段，不應把這些 protection manifest 直接當成 `Phase 1` 修復手段。

正確順序應是：

1. 先穩定量測鏈
2. 完成未保護版 `Phase 1`
3. 再導入 protection overlay 做 A/B
