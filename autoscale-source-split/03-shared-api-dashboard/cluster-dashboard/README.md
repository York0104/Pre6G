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

本地開發時，前端仍可透過 `.env` 讀取：

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

啟動前提示：若 `.env` 缺少 token 或仍保留 `replace-with-issued-token`，前端頁面會顯示 auth notice，且在 API 回 `401` 時給出明確錯誤訊息。

`k3s` / container 部署時，前端也支援 runtime config：

- `PRE6G_DASHBOARD_API_BASE`
- `PRE6G_DASHBOARD_API_TOKEN`

容器啟動時會把這兩個 env 寫入 `env-config.js`，因此後續只改 `ConfigMap/Secret` 並重建 Pod，就能切換 API，不需要重打 frontend image。

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

若使用 preview：

```text
http://<CONTROL_PLANE_IP>:4174
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

## k3s Deployment

前端容器化檔案已放在：

- [Dockerfile](./Dockerfile)
- [nginx/default.conf](./nginx/default.conf)
- [docker-entrypoint.d/40-write-env-config.sh](./docker-entrypoint.d/40-write-env-config.sh)
- [../deploy/k3s/README.md](../deploy/k3s/README.md)

build 指令需以 repo root 作為 context：

```bash
cd /home/icclz2/Pre6G
docker build \
  -f autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/Dockerfile \
  -t harbor.iccl.local:8088/pre6g/cluster-dashboard:0.1 \
  .
```

對 `k3s` 的建議做法是：

1. 先 build 並 push image。
2. 在 `cluster-dashboard-configmap.yaml` 設定 `PRE6G_DASHBOARD_API_BASE`。
3. 在 `cluster-dashboard-secret.yaml` 設定 `PRE6G_DASHBOARD_API_TOKEN`。
4. 套用 [../deploy/k3s/cluster-dashboard-deployment.yaml](../deploy/k3s/cluster-dashboard-deployment.yaml)。

預設 manifest 會以 `NodePort 30080` 暴露 dashboard，並預期 API 可由瀏覽器透過 `NodePort 30081` 連到。

## Not In Scope For This Rebuild

以下內容不作為本次 `k3s` 監控重建驗收項目：

- `Fan-Cycle Experiment`
- YOLO demo control
- thermal experiment live charts
