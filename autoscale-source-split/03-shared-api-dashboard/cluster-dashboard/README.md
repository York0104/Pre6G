# Pre6G Cluster Dashboard

`cluster-dashboard` 是 `Pre6G` 的前端 dashboard。

本次 `k3s` 重建驗收只針對：

- `Cluster Monitor` 頁面

`Fan-Cycle Experiment` 仍依賴 `02-experiment-layer`，不列入本次正式重建驗收。

## API Dependency

前端依賴 `autoscale_api`：

- `GET /api/v1/nodes`
- `GET /api/v1/nodes/status`

目前已驗證前端會透過這兩個 endpoint 顯示：

- 一般 `k3s` nodes
- `RFSoC` external node：`rfsoc4x2-pynq`
- `AP gateway` external node：`openwrt_ap`

這次 external nodes 進 dashboard 的方式是擴充 API 層，不是重寫 React 卡片元件；因此 API 更新完成後，前端重新整理頁面即可看到新節點。

## Environment

前端 `.env`：

```env
VITE_AUTOSCALE_API_BASE=http://<CONTROL_PLANE_IP>:8000
VITE_AUTOSCALE_API_TOKEN=replace-with-issued-token
```

目前常用值：

```env
VITE_AUTOSCALE_API_BASE=http://140.113.179.9:8000
VITE_AUTOSCALE_API_TOKEN=<current-issued-token>
```

若 `autoscale_api` 啟用了 token 驗證，前端必須同步設定 `VITE_AUTOSCALE_API_TOKEN`，否則 `GET /api/v1/nodes` 與 `GET /api/v1/nodes/status` 會直接回 `401 Unauthorized`。

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
- `rfsoc4x2-pynq` 卡片
- `openwrt_ap` 卡片

若 `z590-aorus-xtreme` 顯示 error，這屬於該節點本身既有監控問題，不代表 dashboard 重建失敗。

## Rebuild Steps

1. 先確認 `autoscale-api.service` 已啟動，或至少 `autoscale_api` 可正常回應。
2. 驗證 `GET /api/v1/nodes` 與 `GET /api/v1/nodes/status` 已包含 `rfsoc4x2-pynq` 與 `openwrt_ap`。
3. 設定 `VITE_AUTOSCALE_API_BASE` 指向目前 API，並同步填入 `VITE_AUTOSCALE_API_TOKEN`。
4. 啟動 `run_local_dashboard.sh`。
5. 重新整理瀏覽器頁面，確認 external nodes 已出現於 `Cluster Monitor`。

## Not In Scope For This Rebuild

以下內容不作為本次 `k3s` 監控重建驗收項目：

- `Fan-Cycle Experiment`
- YOLO demo control
- thermal experiment live charts
