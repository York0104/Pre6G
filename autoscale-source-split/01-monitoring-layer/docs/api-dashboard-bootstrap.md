# API And Dashboard Bootstrap

## Scope

本文件整理如何在目前監控層之上，接上 AutoScale API 與 dashboard 所需的最小設定。

## What Exists In This Repo

目前 repo 內已提供：

- `vm_aggregator.py`
- `run_vm_aggregator_once.sh`
- `vm-aggregator-job.incluster.yaml`
- `systemd/autoscale-api.service`
- `systemd/autoscale-api.env.example`
- frontend handoff files

目前 repo 內已包含 `autoscale_api` 與 `cluster-dashboard` 主線內容；這份文件主要整理如何在已重建的 monitoring layer 之上，接上 host-side API 與 frontend。

## Recommended Wiring

### 1. Monitoring backend

- `VictoriaMetrics`
- `Netdata parent`
- `vmagent` / `vmagent-node-local`

這一層已在 `monitoring-rebuild/` 中重建。

### 2. Aggregation layer

- `vm_aggregator.py`
- 若在 host 上呼叫，使用 `monitoring-runtime.host.env`
- 若在 cluster 內呼叫，使用 service DNS 版本設定

### 3. AutoScale API

建議做法：

1. 使用 repo 內的 `03-shared-api-dashboard/autoscale_api/` 作為 API 程式本體
2. 將 [systemd/autoscale-api.env.example](../systemd/autoscale-api.env.example) 複製為實際 env
3. 將 [autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example](../monitoring-runtime.host.env.example) 的端點同步到該 env
4. 優先套用 [systemd/autoscale-api.service](../systemd/autoscale-api.service) 啟動 API；`run_local_api.sh` 僅保留作為手動 fallback

### 4. Dashboard / frontend

frontend 只需要：

- `VITE_AUTOSCALE_API_BASE`
- `VITE_AUTOSCALE_API_TOKEN`（若 API 已開 auth）

可直接依：

- [docs/frontend-api-handoff.md](frontend-api-handoff.md)
- [docs/full-metrics-handoff.md](full-metrics-handoff.md)

## Minimal Validation

### API-side

```bash
export AUTOSCALE_API_BASE=http://140.113.179.9:8000
export AUTOSCALE_API_TOKEN=$(grep '^AUTOSCALE_API_TOKEN=' /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env | cut -d= -f2-)
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" "$AUTOSCALE_API_BASE/"
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" "$AUTOSCALE_API_BASE/api/v1/nodes"
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" "$AUTOSCALE_API_BASE/api/v1/nodes/status"
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" "$AUTOSCALE_API_BASE/api/v1/nodes/icclz3/status"
```

### Monitoring-side

- `bash autoscale-source-split/01-monitoring-layer/run_vm_aggregator_once.sh iccl-cluster-z2`
- `bash autoscale-source-split/01-monitoring-layer/run_vm_aggregator_once.sh icclz3`

## Current Constraint

- `Cluster Monitor` 與 `autoscale_api` 主線已在目前環境驗證可用。
- `icclz1` 現在已是可用 GPU worker，且 `nvidia.com/gpu.shared: 4` 與 `02-experiment-layer` 主線已驗證成功。
- `mirc516-20250605` 若要顯示完整 GPU metrics，仍需先修正主機 NVIDIA driver / userspace mismatch。
- `z590-aorus-xtreme` 仍保留既有磁碟壓力風險，不建議當主要驗證節點。
