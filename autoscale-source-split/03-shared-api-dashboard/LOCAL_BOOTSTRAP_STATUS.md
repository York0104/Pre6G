# Local Bootstrap Status

Date: 2026-05-29
Host: `/home/icclz2/Pre6G`

## What Is Ready

- Monitoring backend 已可供 `k3s` nodes、`RFSoC` 與 `AP gateway` 使用
- Host-side monitoring endpoints 已整理在：
  - [autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env)
- Local API runtime 已驗證可用：
  - [autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service)
  - [autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh](/home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh)
- Local dashboard launcher 已驗證可用：
  - [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh](/home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh)
- Dashboard API base example 已準備：
  - [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/.env.example](/home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/.env.example)
- `autoscale_api` 已能把 external nodes 拉入 dashboard：
  - `rfsoc4x2-pynq`
  - `openwrt_ap`

## Current Local Runtime

### API

目前正式重建建議直接使用 `systemd`：

```bash
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-gateway.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-gateway.env
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-snmp-gateway.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-snmp-gateway.env
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env
sudo cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-gateway.service /etc/systemd/system/
sudo cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-snmp-gateway.service /etc/systemd/system/
sudo cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ap-gateway.service ap-snmp-gateway.service autoscale-api.service
```

驗證：

```bash
systemctl status ap-gateway.service --no-pager
systemctl status ap-snmp-gateway.service --no-pager
systemctl status autoscale-api.service --no-pager
journalctl -u ap-gateway.service -n 50 --no-pager
journalctl -u ap-snmp-gateway.service -n 50 --no-pager
journalctl -u autoscale-api.service -n 50 --no-pager
```

手動除錯時才使用：

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh
```

### Dashboard

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard
bash run_local_dashboard.sh
```

## Current Validated Result

- `GET /api/v1/nodes` 已可列出：
  - 一般 `k3s` nodes
  - `rfsoc4x2-pynq`
  - `openwrt_ap`
- `GET /api/v1/nodes/status` 已可回傳 external node status
- `Cluster Monitor` 前端頁面重新整理後可直接看到 `RFSoC` 與 `AP gateway` 節點卡片

## Minimal Rebuild Sequence

1. 完成 `01-monitoring-layer` 重建與驗證。
2. 確認 `vm_aggregator.py`、`vm_agg_rfsoc.py`、`vm_agg_ap_gateway.py` 都已可輸出資料。
3. 啟動 `autoscale-api.service`。
4. 驗證：
   - `curl http://127.0.0.1:8000/api/v1/nodes | jq`
   - `curl http://127.0.0.1:8000/api/v1/nodes/status | jq`
5. 啟動 `cluster-dashboard/run_local_dashboard.sh`。
6. 瀏覽器重新整理，確認 `Cluster Monitor` 顯示 external nodes。

## Notes

- `run_local_api.sh` 會自動載入 `monitoring-runtime.host.env`（若存在）。
- `collect_node_metrics_csv.py` 目前已可在缺少 `nodes.json` 時 fallback 到 `kubectl get nodes -o json`。
- `z590-aorus-xtreme` 仍不建議作為 dashboard 成功與否的唯一驗證目標，因為它有既有監控問題。
