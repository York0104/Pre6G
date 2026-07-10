# Pre6G Cluster Dashboard

`cluster-dashboard` 是 `Pre6G` 的前端 dashboard。

## Prerequisites

- Node.js `20.19+` or `22.12+`. This project uses Vite 8; Node.js 12 cannot run the current build toolchain.

本次 `k3s` 重建驗收目前涵蓋：

- `Cluster Monitor`
- `LLM Serving Lab`

`Fan-Cycle Experiment` 已於 `2026-06-24` 重建為目前實驗室環境可操作的頁面，但仍依賴 `02-experiment-layer` 與 worker-side `gpu-tempctl-lab`，因此目前屬於 host-side verified path，而非通用 `k3s` productized path。

## Formal Entry

目前正式使用方式已收斂為：

- dashboard 正式入口：`http://140.113.179.9:4174`
- dashboard 實際 API：`http://140.113.179.9:8000`

補充說明：

- `4174` 是正式對外入口
- `8000` 是目前實際可完整驅動 `Cluster Monitor`、`LLM Serving Lab`、`Fan-Cycle Experiment` 的 host-side `autoscale_api`
- `30080` / `30081` 僅保留給 `k3s` NodePort / live-hostpath deployment 驗證，不再是正式入口

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

- `Observation`
  - `Service Overview`
  - `Live Serving Observation`
  - `Replica / Kubernetes Observation`
- `Tasks & Runs`
  - `Single Inference`
  - `Serving Benchmark`
- `Offline Hardware Benchmark`
- fixed serving benchmark profiles (`Smoke` / `Continuous`)
- fixed offline hardware benchmark profiles (`Smoke` / `Continuous`)
- `Recent Runtime History` with filterable recent events

目前這一頁的語意邊界是：

- `Single Inference`：功能驗證、token usage 驗證、單次 latency 觀測
- `Serving Benchmark`：固定 profile 的官方 `vllm bench serve` serving benchmark
- `Offline Hardware Benchmark`：固定 profile 的 `llama-bench` Pascal offline hardware benchmark
- 目前同時支援：
  - 同步 benchmark summary
  - background run progress polling

目前 `Serving Benchmark` 的預設 fixed profiles 為：

- `Smoke`
  - `max_tokens = 64`
  - `concurrency = 1`
  - `request_count = 20`
- `Continuous`
  - `max_tokens = 128`
  - `concurrency = 8`
  - `request_count per chunk = 50`
  - `run mode = repeat chunks until Stop or 30 min safety limit`

兩種 benchmark 在 UI 上的正式解讀：

| UI 區塊 | Official Tool | Target | Capacity View |
| --- | --- | --- | --- |
| `Serving Benchmark` | `vllm bench serve` | live `Gemma 4` serving pod | `Serving Capacity View` |
| `Offline Hardware Benchmark` | `llama-bench` | dedicated `GTX 1080 Ti` benchmark pod | `Hardware Capacity View` |

目前 live 驗證狀態：

- `Serving Benchmark` path 可正常保留在 live `Gemma 4` serving 模型
- 舊的 `vLLM bench throughput` Pascal 路徑已保留為不相容紀錄
- `1080 Ti` 目前正式改走 `llama.cpp + llama-bench`
- 這條路徑提供的是 `Hardware Capacity View`，不可直接與 `4090 + vLLM` live serving metrics 混合加總

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

正式預覽 / 常駐入口：

```text
http://<CONTROL_PLANE_IP>:4174
```

本機正式值：

```text
http://140.113.179.9:4174
```

若 host 內建 `node` 太舊，可直接用 repo 目前已驗證可用的 `node22` preview 腳本：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard
bash run_local_dashboard_preview.sh
```

這條腳本會固定使用：

- `/home/icclz2/.local/node22/bin/node`
- `/home/icclz2/.local/node22/lib/node_modules/npm/bin/npm-cli.js`

因此不依賴系統預設的舊版 `npm`。

## Expected Result

`Cluster Monitor` 應能顯示：

- total nodes
- healthy / degraded / offline counts
- 每台 node card
- selected node detail
- `rfsoc4x2-pynq` 卡片
- `openwrt_ap` 卡片

`LLM Serving Lab` 應能顯示：

- `Runtime Image`
- `Metrics Sample`
- `Metrics Freshness`
- `Generation TPS`
- `Prompt TPS`
- `Waiting Requests`
- `KV Cache Usage`
- `Rate Window`
- `Pod`
- `Node`
- `Pod Phase`
- `Ready Condition`
- `Single Inference` result
- `Target Service`
- `Serving Benchmark` result
- `Offline Hardware Benchmark` result
- `Result Freshness`
- `GPU Preflight`
- `Waiting Requests = N/A — offline benchmark`
- `KV Cache Usage = N/A — offline benchmark`
- recent `Runtime History`

`2026-07-05` 補充：

- `Offline Hardware Benchmark` 已完成 live validation
- `pascal-smoke` 與 `pascal-throughput` 會顯示實際 `pp / tg / pg` 結果
- `Result Freshness` 顯示的是 benchmark 完成後經過多久，不是 scrape freshness
- 若 `GPU Preflight = Contended`，代表本次結果可能受 shared GPU 其他 process 影響

benchmark result 目前應包含：

- `Run Elapsed`
- `Request Throughput`
- `Aggregate Prompt Throughput`
- `Aggregate Generation Throughput`
- `Aggregate Total Throughput`
- `Latency P50`
- `Latency P95`
- `Mean TTFT`
- `P95 TTFT`
- `Mean TPOT`
- `P95 TPOT`
- `Mean ITL`
- `P95 ITL`

若使用 background run，頁面還會顯示：

- `Live Run Progress`

目前 live `LLM Serving Lab` 的 service-wide observation 建議搭配：

- `vLLM /metrics` scrape interval: `1s`
- dashboard workload polling: `1s`
- workload rate window: `3s`
- VictoriaMetrics `search.latencyOffset`: `3s`

這組設定是目前實測下較平衡的預設值；它比原先的 `30s` 查詢偏移即時許多，又比 `0s` 更穩定。
- `Prompt Tokens So Far`
- `Completion Tokens So Far`
- `Total Tokens So Far`
- `Current Prompt TPS`
- `Current Gen TPS`
- `Current Total TPS`
- run-local per-second token chart

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
- 不在 history 保存 prompt preview；只保留 prompt metadata

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

預設 `k3s` manifest 仍會以 `NodePort 30080` 暴露 dashboard，並預期 API 可由瀏覽器透過 `NodePort 30081` 連到；但這條路徑目前僅作為 `k3s` deployment / fallback 說明，不是正式使用入口。

## Not In Scope For This Rebuild

以下內容不作為本次 `k3s` 監控重建驗收項目：

- 將 `Fan-Cycle Experiment` 完整產品化成通用 `k3s` Pod 內 runtime
- 不依賴 host-side SSH / private runtime 的全自足 experiment control
- 更長時間、更多 cycle 的正式研究級 rerun 驗證
