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

`collect_node_metrics_csv.py` 目前已支援：

- 若 `nodes.json` 不存在，會 fallback 到 `kubectl get nodes -o json`

這樣在目前 repo 狀態下，不需要額外補 `nodes.json` 也能完成重建。

## Runtime Dependencies

此 API 依賴以下端點：

- `VM_URL`
- `NETDATA_URL`
- `NETDATA_CHILD_URL`
- `NETDATA_PARENT_BASE_URL`
- `KSM_URL`

建議直接沿用：

- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example)
- [autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env.example)

目前 host-side 驗證可用入口是：

- `VM_URL=http://140.113.179.9:31888`
- `NETDATA_URL=http://140.113.179.9:32163`
- `NETDATA_CHILD_URL=http://140.113.179.9:32163`
- `NETDATA_PARENT_BASE_URL=http://140.113.179.9:32163`
- `KSM_URL=http://140.113.179.9:32080`

## Start Locally

### Preferred For Rebuild

正式重建建議直接使用 `systemd`：

```bash
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env
sudo cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autoscale-api.service
```

注意：上面這一步在 `cp ...autoscale-api.env.example -> autoscale-api.env` 之後，還必須把 `autoscale-api.env` 裡的 `<control-plane-ip>` 全部改成目前主機的真實端點，例如：

- `VM_URL=http://140.113.179.9:31888`
- `NETDATA_PARENT_BASE_URL=http://140.113.179.9:32163`
- `NETDATA_URL=http://140.113.179.9:32163`
- `NETDATA_CHILD_URL=http://140.113.179.9:32163`
- `KSM_URL=http://140.113.179.9:32080`

如果只複製 example 而沒有替換 `<control-plane-ip>`，`autoscale_api` 本身仍可能啟動，但 `/api/v1/full-metrics` 會常見成：RFSoC / AP 正常、所有 k8s nodes 同時失敗。

狀態與 log：

```bash
systemctl status autoscale-api.service --no-pager
journalctl -u autoscale-api.service -n 50 --no-pager
```

本次在 `iccl-cluster-z2` 實際驗證通過的安裝與啟動指令如下：

```bash
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env
sudo cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autoscale-api.service
```


### Manual Fallback

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

### Current Local Runtime

目前建議的 host-side 常駐方式為：

```bash
sudo systemctl enable --now autoscale-api.service
systemctl status autoscale-api.service --no-pager
```

若只是在手動除錯或快速 smoke test，才使用 `run_local_api.sh`。

## Systemd

使用模板：

- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service)
- [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example)

複製 env：

```bash
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env
```

接著務必把 `autoscale-api.env` 內所有 `<control-plane-ip>` 替換成真實值，不可直接保留範例內容。

再填入：

```bash
AUTOSCALE_API_TOKEN=replace-with-a-long-random-token
VM_URL=http://140.113.179.9:31888
NETDATA_PARENT_BASE_URL=http://140.113.179.9:32163
NETDATA_URL=http://140.113.179.9:32163
NETDATA_CHILD_URL=http://140.113.179.9:32163
KSM_URL=http://140.113.179.9:32080
```

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
- `/api/v1/nodes/status` 內兩者皆有 `source` 與 CPU / memory 類欄位

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
