# Pre6G Cluster Dashboard

`cluster-dashboard` 是 `Pre6G` 的前端 dashboard。

本次 `k3s` 重建驗收目前涵蓋：

- `Cluster Monitor`
- `LLM Serving Lab`

`Fan-Cycle Experiment` 已於 `2026-06-24` 重建為目前實驗室環境可操作的頁面，但仍依賴 `02-experiment-layer` 與 worker-side `gpu-tempctl-lab`，因此目前屬於 host-side verified path，而非通用 `k3s` productized path。

## API Dependency

前端依賴 `autoscale_api`：

- `GET /api/v1/nodes`
- `GET /api/v1/nodes/status`
- `GET /api/v1/workloads`
- `GET /api/v1/experiments/fan-cycle/latest`
- `GET /api/v1/experiments/fan-cycle/status`
- `GET /api/v1/experiments/yolo-demo/status`
- `POST /api/v1/experiments/fan-cycle/start`
- `POST /api/v1/experiments/fan-cycle/stop`
- `POST /api/v1/experiments/yolo-demo/start`
- `POST /api/v1/experiments/yolo-demo/stop`
- `POST /api/v1/experiments/yolo-demo/fan-mode/{mode}`

目前已驗證前端會透過這兩個 endpoint 顯示：

- 一般 `k3s` nodes
- `RFSoC` external node：`rfsoc4x2-pynq`
- `AP gateway` external node：`openwrt_ap`

另外 `2026-06-27` 起，`LLM Serving Lab` 會使用 `GET /api/v1/workloads` 與 per-workload status endpoint 顯示：

- `Service Overview`
- `Live Serving Observation`
- `Replica / Kubernetes Observation`

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

## Fan-Cycle Runtime Notes

若要讓 `Fan-Cycle Experiment` 頁籤可真正操作，目前 `autoscale_api` runtime 還需要對應的 experiment env：

- `PRE6G_EXPERIMENT_NAMESPACE`
- `PRE6G_EXPERIMENT_NODE_NAME`
- `PRE6G_EXPERIMENT_NODE_SSH`
- `PRE6G_EXPERIMENT_FOCUS_DEPLOY`
- `PRE6G_EXPERIMENT_BG_DEPLOY`
- `PRE6G_EXPERIMENT_TARGET_MODE`
- `PRE6G_EXPERIMENT_WORKER_REPO`
- `PRE6G_EXPERIMENT_WORKER_VENV`
- `PRE6G_EXPERIMENT_CC_PASSWORD`

這些值建議放在：

- host-side: `autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env`
- private runtime 入口: `config/private-runtime/api/autoscale-api.env`

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

`LLM Serving Lab` 應能顯示：

- `Workload Discovered`
- `Runtime Image`
- `Metrics Sample`
- `Metrics Freshness`
- `Generation TPS`
- `Prompt TPS`
- `Waiting Requests`
- `KV Cache Usage`
- `Query Window`
- `Pod`
- `Node`
- `Pod Phase`
- `Ready Condition`
- `Last Metrics Timestamp`

若 `Gemma 4 vLLM` 已部署且 metrics 可抓取，table 內應可看到：

- `gemma4-e2b-vllm`
- node `iccl-s3-251230`
- `generation TPS`
- `prompt TPS`
- `waiting`
- `KV Cache`
- `Pod Phase`
- `Ready Condition`
- `metrics freshness`

這一版的 UI 原則是：

- 只顯示客觀觀測值
- 不顯示 `AVAILABLE` / `SATURATED` / capacity score
- 不對是否應接新任務做 dashboard 級推論

若 `z590-aorus-xtreme` 顯示 error，這屬於該節點本身既有監控問題，不代表 dashboard 重建失敗。

`Fan-Cycle Experiment` 在目前 host-side rebuild 完成後，應能做到：

- 顯示 latest completed fan-cycle run
- 顯示 fan-cycle execution runtime state
- 顯示 YOLO demo status / events
- 手動切換 `GPU_DEFAULT` / `FIXED_*` fan mode
- 從頁面啟動 / 停止完整 fan-cycle run

若目前還沒有 completed run，頁面仍應可載入控制區塊，而不是直接停在 `404`。

## Rebuild Steps

1. 先確認 `autoscale-api.service` 已啟動，或至少 `autoscale_api` 可正常回應。
2. 驗證 `GET /api/v1/nodes` 與 `GET /api/v1/nodes/status` 已包含 `rfsoc4x2-pynq` 與 `openwrt_ap`。
3. 設定 `VITE_AUTOSCALE_API_BASE` 指向目前 API，並同步填入 `VITE_AUTOSCALE_API_TOKEN`。
4. 啟動 `run_local_dashboard.sh`。
5. 重新整理瀏覽器頁面，確認 external nodes 已出現於 `Cluster Monitor`。
6. 若要驗證 `Fan-Cycle Experiment`：
   - 確認 `autoscale_api` 已載入 `PRE6G_EXPERIMENT_*`
   - 確認 `ssh icclz1-gpu` 與 worker-side `gpu-tempctl-lab` 可用
   - 先在頁面中操作 `Start YOLO Demo`
   - 再操作 `Start Fan-Cycle Run`

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

- 將 `Fan-Cycle Experiment` 完整產品化成通用 `k3s` Pod 內 runtime
- 不依賴 host-side SSH / private runtime 的全自足 experiment control
- 更長時間、更多 cycle 的正式研究級 rerun 驗證
