# Pre6G AutoScale API

## Purpose

`autoscale_api` 是 `Pre6G` 在 `k3s` 監控重建後的查詢入口，負責把：

- Kubernetes node metadata
- VictoriaMetrics 指標
- Netdata host-scoped 資料
- DCGM GPU 指標

整理成固定 JSON schema，供 `Cluster Monitor` dashboard 使用。

本 README 只描述目前已驗證的 `monitoring + cluster monitor` 主線；experiment 相關 API 不列入本次正式重建驗收。

## Main Endpoints

- `GET /`
- `GET /api/v1/nodes`
- `GET /api/v1/nodes/status`
- `GET /api/v1/nodes/{node_name}/status`
- `GET /api/v1/full-metrics`
- `GET /api/v1/full-metrics/{node_name}`

## Runtime Dependencies

此 API 依賴以下端點：

- `VM_URL`
- `NETDATA_URL`
- `NETDATA_CHILD_URL`
- `NETDATA_PARENT_BASE_URL`

建議直接沿用：

- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example)
- [autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example)

## Start Locally

### Preferred

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh
```

這個腳本會：

- 嘗試讀取 `monitoring-runtime.host.env`
- 嘗試讀取 `systemd/autoscale-api.env`
- 使用 repo 根下 `iccl` Python env

### Manual

```bash
cd /home/icclz2/Pre6G
source iccl/bin/activate
cd autoscale-source-split/03-shared-api-dashboard/autoscale_api
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Systemd

使用模板：

- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service)
- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example)

複製 env：

```bash
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env
```

再填入：

```bash
AUTOSCALE_API_TOKEN=replace-with-a-long-random-token
VM_URL=http://<CONTROL_PLANE_IP>:31888
NETDATA_PARENT_BASE_URL=http://<CONTROL_PLANE_IP>:32163
NETDATA_URL=http://<CONTROL_PLANE_IP>:32163
NETDATA_CHILD_URL=http://<CONTROL_PLANE_IP>:32163
```

## Health Check

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/api/v1/nodes | jq
curl http://127.0.0.1:8000/api/v1/nodes/status | jq
```

## Example Response Notes

回傳內容會隨目前 cluster 狀態改變，因此 README 不再固定展示舊環境節點樣本。
請以實際 API 查詢結果為準。

## Validated Scope

截至目前，已驗證：

- `Cluster Monitor` 會使用本 API 成功顯示節點狀態
- `iccl-cluster-z2` 與 `icclz3` 可正常回傳 node status
- GPU node 若 host NVIDIA stack 正常，會回帶 DCGM/GPU 指標

未列入本次驗收：

- `Fan-Cycle Experiment` 頁面
- `02-experiment-layer` 的 workflow
