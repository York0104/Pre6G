# Pre6G AutoScale API

## 1. 專案目的

本專案提供 Pre6G / AutoScale 監控查詢 API，將 Kubernetes、VictoriaMetrics、Netdata、DCGM 等來源的資料整理成固定 JSON 查詢格式，作為後續 LLM、前端介面或 orchestration 模組的統一入口。

目前已完成的核心查詢為：

- `node_list`：提供 cluster 內可查詢節點的固定 inventory
- `node_status`：提供單一節點或全部節點的即時運算資源狀態
- `full_metrics`：提供每個節點 aggregator 的完整原始 JSON

## 2. 目錄結構

```text
autoscale_api/
├─ app/
│  ├─ main.py
│  ├─ routers/
│  │  └─ nodes.py
│  ├─ services/
│  │  ├─ cache_service.py
│  │  ├─ node_inventory_service.py
│  │  └─ node_status_service.py
│  ├─ schemas/
│  │  └─ node.py
│  └─ adapters/
│     └─ k8s_adapter.py
└─ README.md
```

## 3. 分層設計

### `main.py`

FastAPI 入口，負責建立 app 並註冊 routers。

### `routers/`

定義 HTTP API 路徑與 response model。

### `services/`

負責業務邏輯、資料整理與 cache 控制。

### `schemas/`

定義 API 回傳格式（Pydantic models）。

### `adapters/`

負責與外部資料來源互動，例如 Kubernetes API。

目前：

- `node_list` 主要由 Kubernetes Node metadata / status 取得
- `node_status` 目前透過 `vm_aggregator.py` 整合 VM / Netdata / DCGM / K8s 資料後再轉換為固定 API schema

## 4. 已完成 API

### `GET /`

```json
{
  "message": "Pre6G AutoScale API is running"
}
```

### `GET /api/v1/nodes`

回傳所有節點的固定 inventory，包括：

- `node_name`
- `role`
- `k8s_ip`
- `os_image`
- `kernel_version`
- `container_runtime`
- CPU core 數
- memory 大小（MiB）
- NVIDIA GPU inventory

### `GET /api/v1/nodes/{node_name}/status`

回傳指定節點的即時狀態，包括：

- CPU usage %
- CPU used cores
- memory usage %
- memory working set
- disk root usage %
- GPU status / count / frame buffer used

### `GET /api/v1/nodes/status`

回傳所有節點的即時狀態。

### `GET /api/v1/full-metrics`

回傳所有 configured nodes 的完整 aggregator JSON，包括：

- k8s nodes 透過 `vm_aggregator.py`
- RFSoC 透過 `vm_agg_rfsoc.py`
- AP gateway 透過 `vm_agg_ap_gateway.py`

### `GET /api/v1/full-metrics/{node_name}`

回傳指定節點的完整 aggregator JSON。

## 5. 目前設計重點

- `node_list` 與 `node_status` 分離
- `node_list`：固定 inventory
- `node_status`：即時狀態
- `node_list` 主要由 Kubernetes API 取得
- `node_status` 目前透過 `vm_aggregator.collect_state_for_node()` 取得真實資料

目前行為補充：

- `node_list` 已加入簡單 TTL cache
- `node_status` 已加入短 TTL cache
- memory 在 `node_list` 中以 `total_MiB` 呈現
- `gpu.models` 目前主要來自 Kubernetes node labels，例如 `nvidia.com/gpu.product`
- `node_status` 的資料來源為：
  - node metrics：`vm + netdata`
  - gpu metrics：`dcgm_exporter + k8s`
- `node_status` 在 CPU / Memory 會優先讀 `node_pressure_instant`，若 instant 欄位缺值，則 fallback 到 `node_pressure`
- `vm_aggregator` 對 Netdata host-scoped instant chart 已加入 fallback：
  - `urllib` 讀 `/api/v1/data` 若遇到 `404`，會改用 `curl`
  - 若短視窗 `after=-2` 沒資料，會自動退回較長視窗 `after=-60`
  - 這是為了修正像 `ICCL-S3-251230` 這類 mirrored host 的 instant metrics 取值相容性問題

## 6. 回傳範例

### `GET /api/v1/nodes`

```json
{
  "schema": "pre6g.node_list.v1",
  "ts": 1773587432,
  "count": 3,
  "nodes": [
    {
      "node_name": "iccls2",
      "role": "control-plane",
      "k8s_ip": "100.68.32.118",
      "os_image": "Ubuntu 22.04.4 LTS",
      "kernel_version": "6.8.0-101-generic",
      "container_runtime": "containerd://2.2.1",
      "cpu": {
        "cores_total": 64
      },
      "memory": {
        "total_MiB": 63938
      },
      "gpu": {
        "has_gpu": true,
        "count": 1,
        "models": [
          "NVIDIA-GeForce-GTX-1050-Ti"
        ]
      },
      "query_enabled": true
    }
  ]
}
```

### `GET /api/v1/nodes/icclz3/status`

```json
{
  "schema": "pre6g.node_status.v1",
  "ts": 1773589804,
  "node": {
    "node_name": "icclz3",
    "k8s_ip": "100.109.98.27",
    "sources": {
      "node_metrics": "vm+netdata",
      "gpu_metrics": "dcgm_exporter+k8s"
    },
    "cpu": {
      "usage_percent": 20.912547399999998,
      "used_cores": 1.6730037919999998
    },
    "memory": {
      "usage_percent": 22.730276810623977,
      "working_set_bytes": 7630532640,
      "working_set_mib": 7277
    },
    "disk": {
      "root_usage_percent": 75.7723686697809
    },
    "gpu": {
      "status": "no_gpu_or_not_observed",
      "count": 0,
      "fb_used_bytes": 0,
      "fb_used_mib": 0
    }
  }
}
```

## 7. 後續規劃

### Phase 1

- `GET /api/v1/nodes`
- `GET /api/v1/nodes/{node_name}/status`
- `GET /api/v1/nodes/status`

### Phase 2

- `GET /api/v1/namespaces`
- `GET /api/v1/namespaces/{namespace}/workloads`

### Phase 3

- Deployment / Job / Pod profile API
- Cluster summary API
- 背景快取刷新機制
- 設定檔與環境變數整理
- 進一步將 `vm_aggregator` 查詢邏輯 adapter 化

## 8. 執行環境

### 啟動目錄

```bash
cd ~/AutoScale/autoscale_api
```

### 啟動方式

```bash
source ../iccl/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

如需開啟簡單 API 驗證，可先設定：

```bash
export AUTOSCALE_API_TOKEN='replace-with-a-long-random-token'
```

如果使用 repo 內的 systemd service，建議不要把 token 直接寫進 service file。
可改用：

```bash
cp /home/iccls2/AutoScale/systemd/autoscale-api.env.example \
   /home/iccls2/AutoScale/systemd/autoscale-api.env
```

再編輯：

```bash
AUTOSCALE_API_TOKEN=replace-with-a-long-random-token
```

`systemd/autoscale-api.service` 已支援自動讀取這個 env file。

設定後，所有 `/api/*` 路徑都需要帶下列其中一種 header：

```text
Authorization: Bearer <token>
```

或

```text
X-API-Token: <token>
```

`/`、`/docs`、`/openapi.json` 仍可直接存取，方便健康檢查與文件查看。

### 查詢指令

API root：

```bash
curl http://127.0.0.1:8000/
```

Node list：

```bash
curl http://127.0.0.1:8000/api/v1/nodes | jq
```

Single node status：

```bash
curl http://127.0.0.1:8000/api/v1/nodes/icclz3/status | jq
```

All node status：

```bash
curl http://127.0.0.1:8000/api/v1/nodes/status | jq
```

All full metrics：

```bash
curl http://127.0.0.1:8000/api/v1/full-metrics | jq
```

Single full metrics：

```bash
curl http://127.0.0.1:8000/api/v1/full-metrics/iccls2 | jq
```

若已設定 `AUTOSCALE_API_TOKEN`：

```bash
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" \
  http://127.0.0.1:8000/api/v1/nodes/status | jq
```
