# Local Bootstrap Status

Date: 2026-06-24
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
- `k3s` live dashboard / API 已實際部署於 `pre6g-dashboard` namespace：
  - dashboard: `http://140.113.179.9:30080`
  - API: `http://140.113.179.9:30081`
- `Fan-Cycle Experiment` host-side rebuild 已完成：
  - `autoscale_api` 已新增 `fan-cycle` run `status/start/stop`
  - dashboard 頁面已可顯示 runtime state、YOLO demo control、fan-cycle control
  - `autoscale-api.env.example` 已補齊 `PRE6G_EXPERIMENT_*` runtime contract

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

## Current k3s Runtime

本輪已額外完成 `k3s` live 落地，採用：

- [deploy/k3s/live-hostpath/autoscale-api-live.yaml](deploy/k3s/live-hostpath/autoscale-api-live.yaml)
- [deploy/k3s/live-hostpath/cluster-dashboard-live.yaml](deploy/k3s/live-hostpath/cluster-dashboard-live.yaml)

目前設計：

- 兩個 Deployment 都固定在 `icclz2`
- `autoscale_api` 使用 `python:3.12-slim`
- `cluster-dashboard` 使用 `nginx:1.29-alpine`
- frontend 直接讀取 host 上 `cluster-dashboard/dist`
- API Pod 直接掛入 host 上的 `/usr/local/bin/kubectl`

目前檢查方式：

```bash
kubectl -n pre6g-dashboard get pods -o wide
kubectl -n pre6g-dashboard logs deploy/autoscale-api
kubectl -n pre6g-dashboard logs deploy/cluster-dashboard
```

## 2026-06-24 Fan-Cycle Rebuild Notes

本輪已完成：

- 修正 experiment service 內對 repo root / results root 的路徑推導
- 將 `yolo26n-task3-*` 的舊硬編碼控制拓樸收斂到目前 `single_pod_bgload_fan_cycle` 主線預設：
  - `yolo26n-focus`
  - `yolo26n-bg-1`
  - `TARGET_MODE=pod`
- 新增 `fan_cycle_run_service.py`，由 API 直接啟動 / 停止完整 `run_single_pod_bgload_fan_cycle.sh`
- 將實驗 runtime 條件抽成 `PRE6G_EXPERIMENT_*`

本輪未自動執行 live rerun：

- 原因是完整 fan-cycle run 會直接動到目前 `intent-lab` workload、GPU worker 與 worker-side fan control
- 因此這次只做靜態重建、型別 / build 驗證、README / runtime contract 收斂

## Current Validated Result

- `GET /api/v1/nodes` 已可列出：
  - 一般 `k3s` nodes
  - `rfsoc4x2-pynq`
  - `openwrt_ap`
- `GET /api/v1/nodes/status` 已可回傳一般 `k3s` nodes 即時 metrics
- `GET /api/v1/nodes/status` 已可回傳 `rfsoc4x2-pynq` status
- `Cluster Monitor` 前端頁面已可透過 `NodePort 30080` 直接使用
- 一般 `k3s` nodes 已不再因缺 `kubectl` 而全部 fallback 成 `metrics_error`
- external nodes 沒 telemetry 時目前顯示 `OFFLINE`

## Current Gaps

目前尚未在這台主機上完成或驗證：

- `ap-gateway.service`
- `ap-snmp-gateway.service`
- RFSoC SSH key 與 AP SSH key 恢復
- RFSoC / AP 真實 telemetry 恢復
- `k3s` live-hostpath API Pod 內的 experiment control end-to-end 驗證

目前 `autoscale_api` 與 dashboard 已補上 user-level systemd service：

- `~/.config/systemd/user/pre6g-autoscale-api.service`
- `~/.config/systemd/user/pre6g-cluster-dashboard.service`

且截至 `2026-06-03` 已實際 `enable --now` 並驗證：

- API: `http://127.0.0.1:8000/`
- Dashboard preview: `http://127.0.0.1:4174/`

也就是說，目前「API / dashboard 可手動啟動」與「可由目前使用者常駐啟動」都已具備；尚未重建完成的是 external data producers。

另外，目前 `live-hostpath` 仍是本目錄最直接的現場驗證入口；但截至目前 Harbor CA / push-pull workflow 已另外完成，不再需要把 Harbor image 路徑視為 blocked。

若目標是最短驗證路徑，仍建議優先看 `live-hostpath/README.md`；若目標是較正式的 image-based deployment，請同步對照 repo 根層的 `PROJECT_STATUS.md` 與 registry/Harbor 相關文件。

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

## Minimal k3s Rebuild Sequence

1. 先確認 `cluster-dashboard/dist` 已由 Node 22 build 完成。
2. 套用：
   - `deploy/k3s/namespace.yaml`
   - `deploy/k3s/autoscale-api-rbac.yaml`
3. 建立：
   - `autoscale-api-config`
   - `autoscale-api-secret`
   - `cluster-dashboard-config`
   - `cluster-dashboard-secret`
4. 套用：
   - `deploy/k3s/live-hostpath/autoscale-api-live.yaml`
   - `deploy/k3s/live-hostpath/cluster-dashboard-live.yaml`
5. 驗證：
   - `http://140.113.179.9:30081/`
   - `http://140.113.179.9:30080`

## Notes

- repo 內原本保留的 `systemd` 模板仍在：
  - `autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service`
- `config/private-runtime/api/autoscale-api.env` 仍是本輪 experiment runtime 私有值的建議入口。
- 本輪另補了 user-level systemd service，避免一定要修改 `/etc/systemd/system`。
- external nodes 若只有 inventory、沒有 telemetry，前端目前會顯示 `OFFLINE`，這是刻意設計，不代表 dashboard 壞掉。
- `run_local_api.sh` 與 dashboard dev server 是目前最短的重建驗證路徑。
- 目前已驗證的 `k3s` 正式入口請優先看：
  - [deploy/k3s/live-hostpath/README.md](deploy/k3s/live-hostpath/README.md)
