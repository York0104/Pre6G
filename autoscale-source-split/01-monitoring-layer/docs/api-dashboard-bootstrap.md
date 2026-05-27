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

目前 repo 內未包含完整的 `autoscale_api` 應用程式本體，因此這一層以「部署模板 + 對接說明」為主。

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

1. 於 AutoScale 主機部署 `autoscale_api` 程式本體
2. 將 [systemd/autoscale-api.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example) 複製為實際 env
3. 將 [autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example) 的端點同步到該 env
4. 啟動 [systemd/autoscale-api.service](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service)

### 4. Dashboard / frontend

frontend 只需要：

- `API_BASE_URL`
- optional API token

可直接依：

- [docs/frontend-api-handoff.md](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/docs/frontend-api-handoff.md)
- [docs/full-metrics-handoff.md](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/docs/full-metrics-handoff.md)

## Minimal Validation

### API-side

- `curl "$API_BASE_URL/"`
- `curl "$API_BASE_URL/api/v1/nodes"`
- `curl "$API_BASE_URL/api/v1/nodes/status"`
- `curl "$API_BASE_URL/api/v1/nodes/icclz3/status"`

### Monitoring-side

- `bash autoscale-source-split/01-monitoring-layer/run_vm_aggregator_once.sh iccl-cluster-z2`
- `bash autoscale-source-split/01-monitoring-layer/run_vm_aggregator_once.sh icclz3`

## Current Constraint

- `z590-aorus-xtreme` 目前因磁碟滿不建議當成 API / dashboard 驗證目標。
- 若正式版 dashboard 要顯示 GPU 節點完整資訊，需待 `z590-aorus-xtreme` 或正式 GPU worker 恢復穩定後再驗證。
