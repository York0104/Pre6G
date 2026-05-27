# Pre6G Cluster Dashboard

`cluster-dashboard` 是 `Pre6G` 的前端 dashboard。

本次 `k3s` 重建驗收只針對：

- `Cluster Monitor` 頁面

`Fan-Cycle Experiment` 仍依賴 `02-experiment-layer`，不列入本次正式重建驗收。

## API Dependency

前端依賴 `autoscale_api`：

- `GET /api/v1/nodes`
- `GET /api/v1/nodes/status`

## Environment

前端 `.env`：

```env
VITE_AUTOSCALE_API_BASE=http://<CONTROL_PLANE_IP>:8000
```

## Start

### Preferred

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard
bash run_local_dashboard.sh
```

### Manual

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard
npm install
npm run dev -- --host 0.0.0.0 --port 5174
```

## Open

```text
http://<CONTROL_PLANE_IP>:5174
```

## Expected Result

`Cluster Monitor` 應能顯示：

- total nodes
- healthy / degraded / offline counts
- 每台 node card
- selected node detail

## Not In Scope For This Rebuild

以下內容不作為本次 `k3s` 監控重建驗收項目：

- `Fan-Cycle Experiment`
- YOLO demo control
- thermal experiment live charts
