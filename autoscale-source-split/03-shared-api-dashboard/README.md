# 03 Shared API / Dashboard

本層是監控與實驗的共用介面層。`autoscale_api/` 同時提供 monitoring endpoints 與 experiment-control endpoints，因此不歸入單一監控層或實驗層。

## 目錄與檔案說明

| 路徑 | 說明 |
| --- | --- |
| `autoscale_api/` | FastAPI backend，提供 full metrics、node status、experiment control 等 API。 |
| `cluster-dashboard/` | React/Vite frontend dashboard source。 |
| `requirements.txt` | backend/collector 共用 Python dependencies。 |

## `autoscale_api/`

| 路徑 | 說明 |
| --- | --- |
| `README.md` | API 啟動與使用說明。 |
| `app/main.py` | FastAPI app entrypoint 與 router 掛載。 |
| `app/security.py` | API token/security helper。 |
| `app/routers/full_metrics.py` | full metrics API routes，偏監控用途。 |
| `app/routers/nodes.py` | node inventory/status API routes。 |
| `app/routers/experiments.py` | experiment control API routes。 |
| `app/services/cache_service.py` | 簡易 TTL cache。 |
| `app/services/full_metrics_service.py` | full metrics 組裝邏輯。 |
| `app/services/node_inventory_service.py` | node inventory 讀取與整理。 |
| `app/services/node_status_service.py` | 透過 monitoring layer aggregator 取得 node 狀態。 |
| `app/services/fan_cycle_experiment_service.py` | fan-cycle experiment orchestration service。 |
| `app/services/yolo_demo_service.py` | YOLO demo/experiment service helper。 |
| `app/adapters/k8s_adapter.py` | Kubernetes API adapter。 |
| `app/adapters/gpu_static_map_adapter.py` | GPU static map adapter。 |
| `app/adapters/inventory_extra_adapter.py` | 額外 inventory 資料 adapter。 |
| `app/schemas/experiment.py` | experiment-control API schema。 |
| `app/schemas/full_metrics.py` | full metrics API schema。 |
| `app/schemas/node.py` | node inventory/status API schema。 |
| `data/gpu_cuda_cores_map.json` | GPU 型號與 CUDA cores 對照。 |
| `data/node_inventory_extra.json` | 額外 node inventory metadata。 |
| `deploy/inventory-collector.yaml` | inventory collector k8s manifest。 |
| `scripts/fetch_inventory_from_ds.py` | 從 data source 取得 inventory。 |
| `scripts/record_stress_metrics.py` | 定時記錄 stress/aggregator metrics。 |
| `scripts/plot_stress_trends.py` | 繪製 stress metrics 趨勢。 |

## `cluster-dashboard/`

| 路徑 | 說明 |
| --- | --- |
| `README.md` | dashboard 啟動方式。 |
| `.gitignore` | frontend git ignore 設定。 |
| `package.json` / `package-lock.json` | frontend dependencies 與 lockfile。 |
| `src/App.tsx` | dashboard 主要 UI。 |
| `src/App.css` / `src/index.css` | dashboard styles。 |
| `src/main.tsx` | React entrypoint。 |
| `public/favicon.svg` | dashboard favicon。 |
| `public/icons.svg` | dashboard icon sprite/static icons。 |
| `src/assets/hero.png` | dashboard/hero 圖片資產。 |
| `src/assets/react.svg` | React 預設 SVG 資產；保留作為 build/reference。 |
| `src/assets/vite.svg` | Vite 預設 SVG 資產；保留作為 build/reference。 |
| `index.html` | Vite HTML entry。 |
| `vite.config.ts` | Vite 設定。 |
| `tailwind.config.js` / `postcss.config.js` | Tailwind/PostCSS 設定。 |
| `eslint.config.js` | ESLint 設定。 |
| `tsconfig*.json` | TypeScript 設定。 |

## 注意事項

真實 `.env` 未放在本層；請使用 `../current-lab-handoff-private/private-files-to-fill/` 中的 private handoff。
