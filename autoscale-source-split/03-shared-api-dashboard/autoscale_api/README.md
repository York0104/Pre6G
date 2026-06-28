# Pre6G AutoScale API

## Purpose

`autoscale_api` 是 `Pre6G` 在 `k3s` 監控重建後的統一查詢入口，負責把：

- Kubernetes node metadata
- VictoriaMetrics 指標
- Netdata host-scoped 資料
- DCGM GPU 指標
- `RFSoC` external node aggregator 輸出
- `AP gateway` external node aggregator 輸出

整理成固定 JSON schema，供 `Cluster Monitor` 與 `LLM Serving Lab` dashboard 使用。

本 README 以目前已驗證的 `monitoring + cluster monitor` 主線為主，並補充 `2026-06-24` 完成的 `Fan-Cycle Experiment` host-side rebuild 狀態。

## Main Endpoints

- `GET /`
- `GET /api/v1/nodes`
- `GET /api/v1/nodes/status`
- `GET /api/v1/nodes/{node_name}/status`
- `GET /api/v1/full-metrics`
- `GET /api/v1/full-metrics/{node_name}`
- `GET /api/v1/workloads`
- `GET /api/v1/workloads/{namespace}/{workload}/status`
- `GET /api/v1/nodes/{node_name}/workloads`
- `POST /api/v1/llm-lab/inference`
- `POST /api/v1/llm-lab/benchmarks/smoke`
- `GET /api/v1/experiments/fan-cycle/latest`
- `GET /api/v1/experiments/fan-cycle/live`
- `GET /api/v1/experiments/fan-cycle/status`
- `POST /api/v1/experiments/fan-cycle/start`
- `POST /api/v1/experiments/fan-cycle/stop`
- `GET /api/v1/experiments/yolo-demo/status`
- `GET /api/v1/experiments/yolo-demo/events`
- `POST /api/v1/experiments/yolo-demo/start`
- `POST /api/v1/experiments/yolo-demo/stop`
- `POST /api/v1/experiments/yolo-demo/fan-mode/{mode}`

## Current Validated Behavior

### `/api/v1/nodes`

目前會整合：

- live Kubernetes nodes
- `01-monitoring-layer/collector_nodes.json` 中的 external nodes
- `data/node_inventory_extra.json` 補充 metadata

因此目前已驗證能列出：

- 一般 `k3s` nodes
- `rfsoc4x2-pynq`
- `openwrt_ap`

### `/api/v1/nodes/status`

目前會透過 `01-monitoring-layer/collect_node_metrics_csv.py` 載入 node 定義，再呼叫各節點 aggregator：

- `vm_aggregator.py`
- `vm_agg_rfsoc.py`
- `vm_agg_ap_gateway.py`

並統一回傳 dashboard 可直接顯示的 node status。

目前實作上的重要行為：

- 若 `nodes.json` 不存在，會 fallback 到 `kubectl get nodes -o json`
- external nodes telemetry 缺失時，不再強制補成 `0.0`
- dashboard 端目前會把 external nodes 的 telemetry 缺失解讀成 `OFFLINE`

### `/api/v1/workloads`

`2026-06-25` 新增 workload-centric 路由，用來承接 `vLLM` serving metrics，而不污染既有 node schema。

第一版目前支援：

- namespace 預設 `ai-serving`
- `Pod -> ReplicaSet -> Deployment` workload identity 解析
- 由 VictoriaMetrics 查詢 `vllm:*` 指標並聚合成統一 schema
- per-replica `pod_phase` / `ready_condition`
- `metrics_observed_ts` / `freshness_seconds`
- deployment `container image` 回填成 `runtime_image`

核心 aggregation 規則：

- generation TPS: `sum`
- prompt TPS: `sum`
- waiting requests: `sum`
- KV cache usage: `max`

狀態語意：

- `ready`
- `not_ready`
- `metrics_unavailable`

目前這組欄位是為了 dashboard 的 `objective observation only` 視圖設計：

- 顯示客觀 workload state
- 不在 API 內輸出 capacity score 或 scheduler recommendation
- 由前端自行把 `Workload Discovered`、`Metrics Sample`、`Pod Phase`、`Ready Condition` 映射成可驗證畫面欄位

### `/api/v1/llm-lab/inference`

`2026-06-27` 新增最小版 `Single Inference` API，供 `LLM Serving Lab` 送出單次受控 request。

request body:

- `namespace`
- `workload`
- `prompt`
- `max_tokens`
- `temperature`

response:

- `http_status`
- `latency_seconds`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `finish_reason`
- `response_text`

目前設計原則：

- 由 `autoscale_api` 代送到目標 vLLM Service
- 不讓瀏覽器直接打 cluster 內部 Service
- 只允許已發現的 workload
- workload 未 ready 時回 `409`
- service timeout 時回 `504`

### `/api/v1/llm-lab/benchmarks/smoke`

`2026-06-27` 新增固定 profile 的最小 benchmark API。

目前 profile 固定為：

- prompt: fixed short prompt
- max output tokens: `64`
- temperature: `0.0`
- concurrency: `1`
- request count: `20`

response summary:

- `run_id`
- `status`
- `completed_requests`
- `failed_requests`
- `mean_latency_seconds`
- `mean_prompt_tokens`
- `mean_completion_tokens`
- `mean_total_tokens`

## Runtime Dependencies

此 API 依賴以下端點：

- `VM_URL`
- `NETDATA_URL`
- `NETDATA_CHILD_URL`
- `NETDATA_PARENT_BASE_URL`
- `KSM_URL`

建議直接沿用：

- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example](../../01-monitoring-layer/systemd/autoscale-api.env.example)
- [autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example](../../01-monitoring-layer/monitoring-runtime.host.env.example)

目前 host-side 驗證可用入口是：

- `VM_URL=http://140.113.179.9:31888`
- `NETDATA_URL=http://140.113.179.9:32163`
- `NETDATA_CHILD_URL=http://140.113.179.9:32163`
- `NETDATA_PARENT_BASE_URL=http://140.113.179.9:32163`
- `KSM_URL=http://140.113.179.9:32080`

若要啟用 `Fan-Cycle Experiment` 與 `YOLO demo` control，還需要以下 experiment runtime env：

- `PRE6G_EXPERIMENT_NAMESPACE`
- `PRE6G_EXPERIMENT_NODE_NAME`
- `PRE6G_EXPERIMENT_NODE_SSH`
- `PRE6G_EXPERIMENT_FOCUS_DEPLOY`
- `PRE6G_EXPERIMENT_BG_DEPLOY`
- `PRE6G_EXPERIMENT_MEAS_SVC_NAME`
- `PRE6G_EXPERIMENT_TARGET_MODE`
- `PRE6G_EXPERIMENT_WORKER_REPO`
- `PRE6G_EXPERIMENT_WORKER_VENV`
- `PRE6G_EXPERIMENT_CC_PASSWORD`
- `PRE6G_EXPERIMENT_*` 的 cycle / timeout / bgload 參數

這些欄位的公開模板已加入：

- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example](../../01-monitoring-layer/systemd/autoscale-api.env.example)

目前建議把真實值放在：

- host-side runtime：`autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env`
- private runtime 入口：`config/private-runtime/api/autoscale-api.env`

若要啟用 workload-centric `vLLM` API，另外建議設定：

- `PRE6G_WORKLOAD_NAMESPACE=ai-serving`
- `PRE6G_WORKLOAD_QUERY_WINDOW_SECONDS=10`

其中 `10s` 是目前 `LLM Serving Lab` 第一版的預設設定，較適合觀察單次 inference 與短時間 benchmark 的 throughput 變化。

## Fan-Cycle Rebuild Status

截至 `2026-06-24`，已完成：

- 修正 experiment service 的 repo/root path 對齊問題
- 新增 `fan-cycle` run `status/start/stop` API
- 將 YOLO demo 與 fan-cycle runner 的拓樸、SSH、worker repo、coolercontrol 密碼抽成 runtime env
- dashboard 可在沒有 completed run 的情況下仍正常載入 experiment control 畫面

目前仍建議優先使用：

- host-side `run_local_api.sh`
- 或使用者層 systemd 的 `pre6g-autoscale-api.service`

原因是完整 experiment control 仍需要：

- `kubectl`
- `ssh`
- worker-side credential / SSH config
- 對 `icclz1` 的 `gpu-tempctl-lab` 存取

## Start Locally

### Validated path on current host

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh
```

這個腳本會：

- 嘗試讀取 `monitoring-runtime.host.env`
- 嘗試讀取 `systemd/autoscale-api.env`
- 使用 repo 根下 `iccl` Python env

### Manual fallback

```bash
cd /home/icclz2/Pre6G
source iccl/bin/activate
cd autoscale-source-split/03-shared-api-dashboard/autoscale_api
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Optional systemd path

repo 內已提供 `systemd` 模板：

- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service](../../01-monitoring-layer/systemd/autoscale-api.service)
- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example](../../01-monitoring-layer/systemd/autoscale-api.env.example)

但本輪 `icclz2` 重建主線，優先驗證的是手動啟動路徑；目前文件不再宣稱此主機已完成 `autoscale-api.service` 安裝與驗證。

若要改成 `systemd` 常駐，再使用：

```bash
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env
sudo cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autoscale-api.service
```

注意：

- `AUTOSCALE_API_TOKEN` 不可保留 placeholder
- `VM_URL` / `NETDATA_*` / `KSM_URL` 不可保留 `<control-plane-ip>`

## Run In k3s

`autoscale_api` 現在已支援：

- Pod 內優先使用 `in-cluster config`
- 非 Pod 環境 fallback 到本機 `kubeconfig`

因此在 `k3s` 內不需要額外掛 `~/.kube/config`。

容器映像與 manifests 已放在：

- [Dockerfile](./Dockerfile)
- [../deploy/k3s/README.md](../deploy/k3s/README.md)
- [../deploy/k3s/autoscale-api-rbac.yaml](../deploy/k3s/autoscale-api-rbac.yaml)
- [../deploy/k3s/autoscale-api-configmap.example.yaml](../deploy/k3s/autoscale-api-configmap.example.yaml)
- [../deploy/k3s/autoscale-api-secret.example.yaml](../deploy/k3s/autoscale-api-secret.example.yaml)
- [../deploy/k3s/autoscale-api-deployment.yaml](../deploy/k3s/autoscale-api-deployment.yaml)

build 指令需以 repo root 作為 context：

```bash
cd /home/icclz2/Pre6G
docker build \
  -f autoscale-source-split/03-shared-api-dashboard/autoscale_api/Dockerfile \
  -t harbor.iccl.local:8088/pre6g/autoscale-api:0.1 \
  .
```

部署前至少要準備：

- `VM_URL`
- `NETDATA_URL`
- `NETDATA_CHILD_URL`
- `NETDATA_PARENT_BASE_URL`
- `KSM_URL`
- `AUTOSCALE_API_TOKEN`

若要讓 workload API 正常解析 Deployment owner，cluster 內 RBAC 也必須包含：

- `apps/replicasets` `get/list/watch`

API Pod 若要支援 experiment control，RBAC 不只要能讀 `nodes`，還需要：

- `pods`
- `services`
- `events`
- `deployments`
- `deployments/scale`

本 repo 的 `autoscale-api-rbac.yaml` 已在 `2026-06-24` 補上這些權限。

## Health Check

```bash
export AUTOSCALE_API_BASE=http://127.0.0.1:8000
export AUTOSCALE_API_TOKEN=$(grep '^AUTOSCALE_API_TOKEN=' /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env | cut -d= -f2-)
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" "$AUTOSCALE_API_BASE/"
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" "$AUTOSCALE_API_BASE/api/v1/nodes" | jq
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" "$AUTOSCALE_API_BASE/api/v1/nodes/status" | jq
```

建議至少確認：

- `/api/v1/nodes` 內有 `rfsoc4x2-pynq`
- `/api/v1/nodes` 內有 `openwrt_ap`
- `/api/v1/nodes/status` 內有一般 `k3s` nodes
- external nodes 若資料源未恢復，status 仍可能存在，但 telemetry 會是 `null`

## CORS Notes

目前 API 預設允許以下 dashboard origins：

- `localhost:4173` / `4174` / `5173` / `5174`
- `127.0.0.1:4173` / `4174` / `5173` / `5174`
- `140.113.179.9:4173` / `4174` / `5173` / `5174`

這是因為：

- `npm run dev` 常用 `517x`
- `vite preview` 常用 `417x`

若 dashboard 改由其他 host 或 port 提供，瀏覽器可能只會顯示 `Failed to fetch`。
此時請在啟動 `autoscale_api` 前加上：

```bash
export AUTOSCALE_API_CORS_ORIGINS="http://<dashboard-host>:<port>,http://<another-origin>"
```

多個 origin 以逗號分隔即可。

## Current External Node Interpretation

### `rfsoc4x2-pynq`

目前狀態：

- inventory 已接入
- API 路徑已接入
- `vm_agg_rfsoc.py` 已支援 partial fallback

但本機目前仍缺：

- `~/.ssh/id_ed25519_rfsoc`
- 可達的 `100.91.37.32:9100`
- 可達的 `100.91.37.32:19999`
- 可達的 `ssh xilinx@100.91.37.32`

因此目前 dashboard 上會看到節點，但 telemetry 可能缺失並顯示 `OFFLINE`。

### `openwrt_ap`

目前狀態：

- inventory 已接入
- API 路徑已接入

但本機目前仍缺：

- `~/.ssh/openwrt_ap_ed25519`
- `ap-gateway.service` producer 驗證
- `ap-snmp-gateway.service` producer 驗證
- VictoriaMetrics 中的 `ap_*` metrics

因此目前 dashboard 上會看到節點，但 telemetry 可能缺失並顯示 `OFFLINE`。

## Example Response Notes

回傳內容會隨目前 cluster 狀態改變，因此 README 不再固定展示舊環境節點樣本。
請以實際 API 查詢結果為準。

## Validated Scope

截至目前，已驗證：

- `Cluster Monitor` 會使用本 API 成功顯示一般 `k3s` nodes
- `Cluster Monitor` 會顯示 `rfsoc4x2-pynq`
- `Cluster Monitor` 會顯示 `openwrt_ap`
- host-side `run_local_api.sh` 可在目前環境直接啟動 API
- `Fan-Cycle Experiment` 的 host-side API / frontend wiring 已重建完成
- `cluster-dashboard` 可在 Node 22 成功 build，包含新的 experiment control UI

本次未在此 turn 自動做 live experiment rerun 驗證：

- 完整 `fan-cycle start -> worker thermal cycle -> completed run` 實跑
- `k3s` Pod 內 experiment control 的 end-to-end 驗證

原因是這兩項都會直接影響目前實驗室 workload / GPU worker 狀態。
