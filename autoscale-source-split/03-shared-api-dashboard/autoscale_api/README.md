# Pre6G AutoScale API

## Purpose

`autoscale_api` 是 `Pre6G` 在 `k3s` 監控重建後的統一查詢入口，負責把：

- Kubernetes node metadata
- VictoriaMetrics 指標
- Netdata host-scoped 資料
- DCGM GPU 指標
- `RFSoC` external node aggregator 輸出
- `AP gateway` external node aggregator 輸出

整理成固定 JSON schema，供 `Cluster Monitor` dashboard 使用。

本 README 只描述目前已驗證的 `monitoring + cluster monitor` 主線；experiment 相關 API 不列入本次正式重建驗收。

## Main Endpoints

- `GET /`
- `GET /api/v1/nodes`
- `GET /api/v1/nodes/status`
- `GET /api/v1/nodes/{node_name}/status`
- `GET /api/v1/full-metrics`
- `GET /api/v1/full-metrics/{node_name}`

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

API Pod 另外需要讀取 `nodes` 的 RBAC，否則 `/api/v1/nodes` 會失敗。

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

未列入本次驗收：

- `Fan-Cycle Experiment` 頁面
- `02-experiment-layer` 的 workflow
