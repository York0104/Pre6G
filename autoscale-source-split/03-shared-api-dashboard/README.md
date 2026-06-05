# 03 Shared API / Dashboard

本層是目前 `Pre6G` 監控重建完成後的共用介面層，提供：

- `autoscale_api/`：FastAPI backend
- `cluster-dashboard/`：React/Vite frontend

目前正式驗證範圍是 `Cluster Monitor` 主線，且已包含：

- 一般 `k3s` 節點
- `RFSoC` external node：`rfsoc4x2-pynq`
- `AP gateway` external node：`openwrt_ap`

`Fan-Cycle Experiment` 與其他 experiment-control 相關 API 仍保留，但不列入本次正式重建驗收。

## 目前資料流

`cluster-dashboard` 目前透過 `autoscale_api` 的兩個節點 API 顯示主畫面：

- `GET /api/v1/nodes`
- `GET /api/v1/nodes/status`

目前這兩個 endpoint 會同時整合：

- Kubernetes node inventory
- `01-monitoring-layer/collector_nodes.json` 中定義的 external nodes
- `autoscale_api/data/node_inventory_extra.json` 中的補充 metadata

因此前端重新整理後，應可直接看到：

- `rfsoc4x2-pynq`
- `openwrt_ap`

不需要額外修改 React 卡片元件。

## 目錄與檔案說明

| 路徑 | 說明 |
| --- | --- |
| `autoscale_api/` | FastAPI backend，提供 node inventory/status、full metrics 與 experiment control API。 |
| `cluster-dashboard/` | React/Vite frontend dashboard source。 |
| `deploy/k3s/` | API + dashboard 的 `k3s` manifests、RBAC 與建置說明。 |
| `requirements.txt` | backend/collector 共用 Python dependencies。 |
| `LOCAL_BOOTSTRAP_STATUS.md` | 本機啟動與目前重建狀態摘要。 |

## `autoscale_api/`

| 路徑 | 說明 |
| --- | --- |
| `README.md` | API 啟動、重建與驗證說明。 |
| `Dockerfile` | `k3s` / container 部署用 backend image 定義。 |
| `app/main.py` | FastAPI app entrypoint 與 router 掛載。 |
| `app/security.py` | API token/security helper。 |
| `app/routers/full_metrics.py` | full metrics API routes，偏監控用途。 |
| `app/routers/nodes.py` | node inventory/status API routes。 |
| `app/routers/experiments.py` | experiment control API routes。 |
| `app/services/cache_service.py` | 簡易 TTL cache。 |
| `app/services/full_metrics_service.py` | full metrics 組裝邏輯。 |
| `app/services/node_inventory_service.py` | 整合 k8s nodes、external nodes 與 extra metadata。 |
| `app/services/node_status_service.py` | 透過 monitoring layer aggregator 取得節點狀態，已支援 `k8s` / `RFSoC` / `AP gateway`。 |
| `app/services/fan_cycle_experiment_service.py` | fan-cycle experiment orchestration service。 |
| `app/services/yolo_demo_service.py` | YOLO demo/experiment service helper。 |
| `app/adapters/k8s_adapter.py` | Kubernetes API adapter。 |
| `app/adapters/gpu_static_map_adapter.py` | GPU static map adapter。 |
| `app/adapters/inventory_extra_adapter.py` | 額外 inventory 資料 adapter。 |
| `app/schemas/experiment.py` | experiment-control API schema。 |
| `app/schemas/full_metrics.py` | full metrics API schema。 |
| `app/schemas/node.py` | node inventory/status API schema。 |
| `data/gpu_cuda_cores_map.json` | GPU 型號與 CUDA cores 對照。 |
| `data/node_inventory_extra.json` | 額外 node inventory metadata，已包含 `RFSoC` 與 `AP gateway`。 |
| `deploy/inventory-collector.yaml` | inventory collector k8s manifest。 |
| `scripts/fetch_inventory_from_ds.py` | 從 data source 取得 inventory。 |
| `scripts/record_stress_metrics.py` | 定時記錄 stress/aggregator metrics。 |
| `scripts/plot_stress_trends.py` | 繪製 stress metrics 趨勢。 |

## `cluster-dashboard/`

| 路徑 | 說明 |
| --- | --- |
| `README.md` | dashboard 啟動與驗證方式。 |
| `Dockerfile` | `k3s` / container 部署用 frontend image 定義。 |
| `.gitignore` | frontend git ignore 設定。 |
| `package.json` / `package-lock.json` | frontend dependencies 與 lockfile。 |
| `src/App.tsx` | dashboard 主要 UI。 |
| `src/App.css` / `src/index.css` | dashboard styles。 |
| `src/main.tsx` | React entrypoint。 |
| `public/favicon.svg` | dashboard favicon。 |
| `public/icons.svg` | dashboard icon sprite/static icons。 |
| `public/env-config.js` | runtime config 預設入口；`k3s` 容器啟動時會覆寫。 |
| `src/assets/hero.png` | dashboard/hero 圖片資產。 |
| `src/assets/react.svg` | React 預設 SVG 資產；保留作為 build/reference。 |
| `src/assets/vite.svg` | Vite 預設 SVG 資產；保留作為 build/reference。 |
| `index.html` | Vite HTML entry。 |
| `vite.config.ts` | Vite 設定。 |
| `nginx/default.conf` | container 版靜態站台設定。 |
| `docker-entrypoint.d/40-write-env-config.sh` | 容器啟動時寫入 frontend runtime config。 |
| `tailwind.config.js` / `postcss.config.js` | Tailwind/PostCSS 設定。 |
| `eslint.config.js` | ESLint 設定。 |
| `tsconfig*.json` | TypeScript 設定。 |

## 目前重建步驟

1. 先完成 `01-monitoring-layer` 主線，確認：
   - `vm_aggregator.py`
   - `vm_agg_rfsoc.py`
   - `vm_agg_ap_gateway.py`
   都可正常輸出資料。
2. 啟動 API：
   - 正式重建優先使用 `systemd` 的 `autoscale-api.service`
   - `autoscale_api/run_local_api.sh` 僅保留作為手動 fallback
3. 驗證 API：
   - `GET /api/v1/nodes`
   - `GET /api/v1/nodes/status`
   需能看到 `rfsoc4x2-pynq` 與 `openwrt_ap`。
4. 啟動 dashboard：
   - 設定 `VITE_AUTOSCALE_API_BASE`
   - 若 API 已啟用 auth，也同步設定 `VITE_AUTOSCALE_API_TOKEN`
   - 執行 `cluster-dashboard/run_local_dashboard.sh`
5. 重新整理前端頁面，確認 external nodes 已出現在 `Cluster Monitor`。

## k3s 部署

現在 repo 內已附上完整 `k3s` 落地樣板，建議入口為：

- [deploy/k3s/README.md](./deploy/k3s/README.md)

這條路徑包含：

- backend/frontend Docker build 指令
- `Deployment` / `Service` / `RBAC`
- `ConfigMap` / `Secret` 範本
- `NodePort` 與可選 `Ingress`

另外，若目標是直接在目前 `icclz2` 完成可用部署，已實際驗證的入口是：

- [deploy/k3s/live-hostpath/README.md](./deploy/k3s/live-hostpath/README.md)

若目標是穩定常駐而非互動式開發，建議優先採用這條 `k3s` 路徑，而不是長時間用 `tmux + vite dev`。

## 注意事項

- 若目標是目前可交付的 `k3s` 監控重建，請優先使用 `autoscale_api/README.md` 與 `cluster-dashboard/README.md`。
- `app/services/fan_cycle_experiment_service.py`、`app/services/yolo_demo_service.py` 與 experiment routers 仍屬未驗證的實驗層接口。
- 真實 `.env` 未放在本層；請使用 `../current-lab-handoff-private/private-files-to-fill/` 中的 private handoff。
