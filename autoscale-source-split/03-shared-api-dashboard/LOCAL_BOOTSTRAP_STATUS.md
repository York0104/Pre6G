# Local Bootstrap Status

Date: 2026-06-03
Host: `/home/icclz2/Pre6G`

## What Is Ready

- Monitoring backend 已可供目前 `k3s` nodes 使用
- Host-side monitoring endpoints 已整理在：
  - [autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env](../01-monitoring-layer/monitoring-runtime.host.env)
- Local API runtime 已驗證可用：
  - [autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh](autoscale_api/run_local_api.sh)
- Local dashboard launcher 已驗證可用：
  - [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh](cluster-dashboard/run_local_dashboard.sh)
- Local dashboard preview launcher 已建立：
  - [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard_preview.sh](cluster-dashboard/run_local_dashboard_preview.sh)
- Dashboard API base env 已建立：
  - [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/.env](cluster-dashboard/.env)
- `autoscale_api` 已能把 external nodes 拉入 dashboard：
  - `rfsoc4x2-pynq`
  - `openwrt_ap`

## Current Local Runtime

### API

本輪在 `icclz2` 已同時驗證：

- 手動啟動
- user-level systemd 常駐啟動

手動啟動方式：

```bash
cd /home/icclz2/Pre6G
bash autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh
```

目前已確認：

- Python venv 位於 `/home/icclz2/Pre6G/iccl`
- `run_local_api.sh` 會載入：
  - `autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env`
  - `autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env`
- API 會綁在 `0.0.0.0:8000`

常見問題：

- 若出現 `address already in use`，代表已有另一個 `uvicorn` process 佔住 `8000`
- `schema` field 的 Pydantic warning 目前只是警告，不會阻止 API 啟動

必要時可先清掉舊 process：

```bash
pkill -f "uvicorn app.main:app"
```

目前 user-level systemd service：

```bash
systemctl --user status pre6g-autoscale-api.service
```

### Dashboard

本輪 dashboard 使用本機安裝的 Node 22：

```bash
export PATH=/home/icclz2/.local/node22/bin:$PATH
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard
bash run_local_dashboard.sh
```

目前已驗證：

- `npm install` 可完成
- `npm run build` 成功
- `dist/` 已產出
- `vite preview` 可由 user-level systemd 常駐啟動

目前 user-level systemd service：

```bash
systemctl --user status pre6g-cluster-dashboard.service
```

## Current Validated Result

- `GET /api/v1/nodes` 已可列出：
  - 一般 `k3s` nodes
  - `rfsoc4x2-pynq`
  - `openwrt_ap`
- `GET /api/v1/nodes/status` 已可回傳 external node status
- `Cluster Monitor` 前端頁面可看到 external node 卡片
- external nodes 沒 telemetry 時目前顯示 `OFFLINE`

## Current Gaps

目前尚未在這台主機上完成或驗證：

- `ap-gateway.service`
- `ap-snmp-gateway.service`
- RFSoC SSH key 與 AP SSH key 恢復
- RFSoC / AP 真實 telemetry 恢復

目前 `autoscale_api` 與 dashboard 已補上 user-level systemd service：

- `~/.config/systemd/user/pre6g-autoscale-api.service`
- `~/.config/systemd/user/pre6g-cluster-dashboard.service`

且截至 `2026-06-03` 已實際 `enable --now` 並驗證：

- API: `http://127.0.0.1:8000/`
- Dashboard preview: `http://127.0.0.1:4174/`

也就是說，目前「API / dashboard 可手動啟動」與「可由目前使用者常駐啟動」都已具備；尚未重建完成的是 external data producers。

## Minimal Rebuild Sequence

1. 完成 `01-monitoring-layer` 重建與驗證。
2. 建立或更新：
   - `monitoring-runtime.host.env`
   - `systemd/autoscale-api.env`
3. 啟動 API：
   - `bash autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh`
4. 驗證：
   - `curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/v1/nodes`
   - `curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/v1/nodes/status`
5. 啟動 dashboard：
   - `export PATH=/home/icclz2/.local/node22/bin:$PATH`
   - `bash run_local_dashboard.sh`
6. 重新整理瀏覽器，確認 `Cluster Monitor` 顯示資料。

## Notes

- repo 內原本保留的 `systemd` 模板仍在：
  - `autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service`
- 本輪另補了 user-level systemd service，避免一定要修改 `/etc/systemd/system`。
- external nodes 若只有 inventory、沒有 telemetry，前端目前會顯示 `OFFLINE`，這是刻意設計，不代表 dashboard 壞掉。
- `run_local_api.sh` 與 dashboard dev server 是目前最短的重建驗證路徑。
