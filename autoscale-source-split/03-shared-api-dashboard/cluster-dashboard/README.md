# Pre6G Cluster Dashboard

`cluster-dashboard` 是 Pre6G AutoScale 專案的前端監控介面，使用 `React + TypeScript + Vite + Tailwind CSS + Recharts` 建置，主要提供兩個展示頁面：

- `Cluster Monitor`：叢集節點總覽與即時資源監控
- `Fan-Cycle Experiment`：YOLO 單 Pod 熱異常示範、GPU 熱狀態與服務延遲觀測

本 README 整理了這次介面設計成果、目前功能、啟動方式與展示操作流程。

## Design Goals

本次介面設計聚焦三件事：

- 把 Kubernetes heterogeneous cluster 的節點狀態做成可展示的 dashboard
- 把 GPU fan / thermal anomaly 與 YOLO inference degradation 放到同一個實驗頁面
- 讓實驗展示不只看靜態圖，而是能直接在網頁中觀察 live metrics、事件與服務狀態

整體視覺採深色監控面板風格，重點是：

- 狀態卡片明確
- 左右資訊分區清楚
- 重點圖表集中展示
- 可支援簡報、展示與現場操作

## Pages

### 1. Cluster Monitor

用來展示整體叢集健康狀態與單節點細節。

主要內容：

- Cluster summary cards
  - `Total Nodes`
  - `Healthy`
  - `Degraded`
  - `Offline`
  - `Avg CPU`
  - `Avg Memory`
- Node cards
  - 顯示 node name、role、k8s IP、CPU、GPU 型號
  - 顯示 CPU / Memory / Disk usage 與 GPU FB used
- Selected Node Detail
  - 顯示 OS、Kernel、Runtime、CPU、Memory、GPU 基本資訊
  - 顯示所選 node 的 CPU / Memory / Disk / GPU FB used 近端歷史曲線

健康狀態判斷邏輯：

- `healthy`：metrics 正常，且 CPU / Memory / Disk 未達高風險閾值
- `degraded`：metrics source error、GPU metrics error，或 CPU / Memory / Disk 過高
- `offline`：inventory 有 node，但沒有對應 status

### 2. Fan-Cycle Experiment

用來展示 `single-pod + background GPU load + fan control` 的 YOLO 實驗頁面。

目前頁面配置為：

- 頂部：`Fan-Cycle Experiment Console`
- 頂部：`Thermal State`
- 中段左側：
  - `YOLO Service`
  - `Experiment Control`
- 中段右側：
  - `GPU Temperature / Fan Speed`
  - `SM Clock`
  - `GPU Utilization`
  - `Server Latency`
- 底部：
  - `Event Timeline`

這個頁面結合了兩種資料來源：

- 最新一次 fan-cycle experiment 結果
- 目前 YOLO demo 執行狀態與 live GPU metrics

## Fan-Cycle Experiment Design

### YOLO Service

`YOLO Service` 用來描述目前 YOLO demo 的執行對象與狀態：

- `Current Run`
  - 目前 demo 的執行 ID
- `Focus Pod`
  - 單一提供 YOLO inference 的 pod
- `Target URL`
  - serial request client 持續送 request 的 endpoint
- `YOLO Demo Status`
  - `Running / Stopped / Starting / Error`
- `Start YOLO Demo`
  - 啟動 demo
- `Stop YOLO Demo`
  - 停止 demo
- `Start E2E Capture / Pause Capture`
  - 控制前端是否持續抓取 live metrics 與事件

### Experiment Control

`Experiment Control` 用來手動套用 GPU fan mode。

目前支援固定模式：

- `GPU_DEFAULT`
- `FIXED_5`
- `FIXED_15`
- `FIXED_20`
- `FIXED_25`

目前不提供 `CUSTOM_PERCENT`，目的是讓展示流程固定且可重現。

### Thermal State

`Thermal State` 會顯示目前觀測到的 live 指標：

- `GPU Temp`
- `Fan Speed`
- `SM Clock`
- `GPU Util`
- `Server Latency`
- `E2E Latency`

其中：

- GPU 指標來自 worker 端即時查詢
- latency 指標來自當前 demo run 的最新量測資料

### Event Timeline

`Event Timeline` 已改為 YOLO demo 的即時事件流，不再使用舊的 fan-cycle phase log。

目前事件會記錄類似：

- `demo_start_requested`
- `focus_scaled`
- `bg_scaled`
- `focus_ready`
- `focus_pod_resolved`
- `target_url_resolved`
- `serial_client_started`
- `bgload_started`
- `fan_mode_applied`
- `demo_stop_requested`
- `serial_client_stopped`
- `bgload_stopped`
- `focus_scaled_down`
- `bg_scaled_down`
- `demo_stopped`

## YOLO Demo Workflow

當按下 `Start YOLO Demo` 時，系統會依序做：

1. 把 focus deploy 保持成單 pod
2. 把 background deploy 關閉
3. 找出 `FOCUS_POD`
4. 找出 `TARGET_URL`
5. 啟動 serial request client 持續送 YOLO inference requests
6. 啟動 worker 端 GPU background load

當按下 `Stop YOLO Demo` 時，系統會：

1. 停掉 serial request client
2. 停掉 GPU background load
3. 把 deploy scale 回 `0`
4. 清理 runtime state

## Live Update Behavior

目前 `Fan-Cycle Experiment` 分頁的前端 polling 設定為 `1s`。

會定期更新：

- YOLO demo status
- YOLO demo event timeline
- live GPU metrics
- Server latency / E2E latency

注意：

- 前端輪詢頻率是 `1s`
- 實際資料變化頻率仍取決於後端資料是否有新的樣本
- GPU metrics 接近即時
- `Server Latency` 需要等待新的 request measurement 寫入後才會變動

## API Dependencies

此 dashboard 依賴 `autoscale_api` 提供的 API。

### Cluster Monitor APIs

- `GET /api/v1/nodes`
- `GET /api/v1/nodes/status`

### Fan-Cycle / YOLO Demo APIs

- `GET /api/v1/experiments/fan-cycle/latest`
- `GET /api/v1/experiments/fan-cycle/live`
- `GET /api/v1/experiments/yolo-demo/status`
- `GET /api/v1/experiments/yolo-demo/events`
- `POST /api/v1/experiments/yolo-demo/start`
- `POST /api/v1/experiments/yolo-demo/stop`
- `POST /api/v1/experiments/yolo-demo/fan-mode/{mode}`

## Environment

目前前端 `.env` 設定為：

```env
VITE_AUTOSCALE_API_BASE=http://100.68.32.118:8000
```

如果後端位址變更，請同步修改 `cluster-dashboard/.env`。

## Run

### Backend

```bash
cd ~/AutoScale/autoscale_api
source ../iccl/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd ~/AutoScale/cluster-dashboard
npm run dev -- --host 0.0.0.0 --port 5174
```

### Open From Windows

```bash
http://100.68.32.118:5174
```

## Recommended Demo Flow

建議展示流程如下：

1. 先開啟 `Cluster Monitor`
2. 介紹 cluster node cards 與 health summary
3. 切到 `Fan-Cycle Experiment`
4. 說明 `YOLO Service`、`Experiment Control`、`Thermal State`
5. 按下 `Start YOLO Demo`
6. 観察：
   - `GPU Temperature / Fan Speed`
   - `SM Clock`
   - `GPU Utilization`
   - `Server Latency`
   - `Event Timeline`
7. 視需要切換 fan mode
8. 完成後按下 `Stop YOLO Demo`

## Current Implementation Notes

目前系統特性如下：

- `Cluster Monitor` 為真實 API 驅動
- `Fan-Cycle Experiment` 為真實資料驅動，不是純 mock page
- `Event Timeline` 已改為 YOLO demo live events
- `Start YOLO Demo` 與 `Stop YOLO Demo` 已接到後端控制
- fan mode 採固定選項，避免展示時輸入不一致
- 當 YOLO demo 未執行時，`Server Latency` 與 `E2E Latency` 會顯示為空或 `N/A`

## Project Structure

```text
cluster-dashboard/
├── src/
│   ├── App.tsx
│   ├── index.css
│   └── main.tsx
├── .env
├── package.json
└── README.md
```

## Future Improvements

後續可以持續擴充：

- 將 `Current p95-like Signal` 改成真正的 rolling live p95
- 增加更完整的 experiment status badge 與操作回饋
- 增加 fan mode 切換結果的明確事件標記
- 把 experiment result 與 historical run browser 做成獨立頁面
- 補更多 GPU metrics，例如：
  - `temperature`
  - `utilization`
  - `power draw`
  - `fan state`
  - `P-state`

## Notes

這份 dashboard 主要用於：

- Pre6G cluster monitoring 展示
- GPU thermal anomaly / cooling fault 實驗展示
- YOLO inference degradation 與 thermal state 關聯觀察

若後端 API、Kubernetes deploy 名稱或 worker 節點位址變更，請同步更新前端與 `autoscale_api` 的實驗服務設定。
