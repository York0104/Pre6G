# Full Metrics API Handoff

本文件提供給需要持續讀取 Pre6G AutoScale 所有節點 raw JSON 的前端或外部整合者。

## 1. 目的

整合者應只透過 AutoScale API 讀取資料，不需要也不應直接存取：

- master SSH
- Kubernetes kubeconfig
- VictoriaMetrics
- Netdata
- RFSoC SSH
- AP SSH / SNMP

建議整合方式：

```text
Frontend / External Service
  -> AutoScale API
  -> /api/v1/full-metrics
  -> /api/v1/full-metrics/{node_name}
```

## 2. 你會收到什麼

系統提供者會提供：

- `API_BASE_URL`
- 是否啟用 API token
- 若有啟用 token，會另外提供 token 值
- 可查詢的 `node_name` 清單

範例：

```env
AUTOSCALE_API_BASE=http://100.68.32.118:8000
AUTOSCALE_API_TOKEN=replace-with-issued-token
```

## 3. 可用 API

### `GET /`

用途：

- 健康檢查
- 確認 API 在線

### `GET /api/v1/full-metrics`

用途：

- 取得所有 configured nodes 的完整 raw JSON
- 適合總覽頁或資料同步器

### `GET /api/v1/full-metrics/{node_name}`

用途：

- 取得單一節點的完整 raw JSON
- 適合詳細頁或單節點監看

## 4. 回傳格式重點

`GET /api/v1/full-metrics` 回傳結構：

```json
{
  "schema": "pre6g.full_metrics_list.v1",
  "ts": 1710000000,
  "count": 8,
  "ok_count": 6,
  "error_count": 2,
  "nodes": [
    {
      "node_name": "icclz1",
      "node_type": "k8s",
      "aggregator": "vm_aggregator.py",
      "payload": {
        "collector_status": "ok",
        "schema": "intentcontinuum.state.v6"
      }
    }
  ]
}
```

欄位說明：

- `ts`: 這次 API 回應時間
- `count`: 這次回傳節點數
- `ok_count`: `payload.collector_status = ok` 的節點數
- `error_count`: `payload.collector_status = error` 的節點數
- `nodes[].payload`: 節點的完整 raw JSON

## 5. `collector_status` 解讀

- `ok`
  - 代表該節點這次成功取得 raw JSON
- `error`
  - 代表該節點這次採集失敗或上游來源暫時不可用
  - 前端應將其視為 monitoring gap，而不是網站本身故障

## 6. 建議輪詢頻率

- 全部節點：每 `3-5` 秒輪詢一次 `GET /api/v1/full-metrics`
- 單節點詳細頁：每 `1-3` 秒輪詢一次 `GET /api/v1/full-metrics/{node_name}`

不建議以 `1s` 以下頻率輪詢全部節點。

## 7. 認證方式

如果 API token 未啟用，直接呼叫即可。

如果 API token 已啟用，請在每次 request 帶其中一種 header：

```http
Authorization: Bearer <token>
```

或：

```http
X-API-Token: <token>
```

## 8. curl 範例

不帶 token：

```bash
curl "$API_BASE_URL/api/v1/full-metrics" | jq
```

帶 token：

```bash
curl \
  -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" \
  "$API_BASE_URL/api/v1/full-metrics" | jq
```

查單一節點：

```bash
curl \
  -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" \
  "$API_BASE_URL/api/v1/full-metrics/icclz1" | jq
```

## 9. 每 30 秒持續落地 raw JSON 與 CSV

repo 已提供一個範例 wrapper：

- [run_full_metrics_api_collector.sh](/home/iccls2/AutoScale/run_full_metrics_api_collector.sh)

用途：

- 每隔固定秒數呼叫 `GET /api/v1/full-metrics`
- 每個節點各自輸出一份 CSV
- 每個節點各自輸出一份 raw JSONL
- 另外保存整包 API 回應的 `raw_json/full_metrics_response.jsonl`

預設輸出目錄格式：

```text
$HOME/node_metric_csv_logs/YYYYMMDD_HHMMSS/
```

例如：

```text
/home/iccls2/node_metric_csv_logs/20260519_004958
```

執行範例：

```bash
API_BASE_URL=http://100.68.32.118:8000 \
API_TOKEN=replace-with-issued-token \
INTERVAL_SECONDS=30 \
bash /home/iccls2/AutoScale/run_full_metrics_api_collector.sh
```

若不需要 token，可省略 `API_TOKEN`。

輸出結構範例：

```text
$HOME/node_metric_csv_logs/20260519_004958/
├── ap_gateway_openwrt_ap.csv
├── k8s_iccls2.csv
├── k8s_icclz1.csv
├── rfsoc_rfsoc4x2-pynq.csv
├── collector.log
├── nodes_manifest.json
└── raw_json/
    ├── ap_gateway_openwrt_ap.jsonl
    ├── full_metrics_response.jsonl
    ├── k8s_iccls2.jsonl
    ├── k8s_icclz1.jsonl
    └── rfsoc_rfsoc4x2-pynq.jsonl
```

## 10. JavaScript 範例

```ts
const API_BASE = import.meta.env.VITE_AUTOSCALE_API_BASE;
const API_TOKEN = import.meta.env.VITE_AUTOSCALE_API_TOKEN;

function buildHeaders(): HeadersInit {
  if (!API_TOKEN) return {};
  return {
    Authorization: `Bearer ${API_TOKEN}`,
  };
}

export async function fetchAllFullMetrics() {
  const res = await fetch(`${API_BASE}/api/v1/full-metrics`, {
    headers: buildHeaders(),
  });
  if (!res.ok) throw new Error(`fetchAllFullMetrics failed: ${res.status}`);
  return res.json();
}

export async function fetchNodeFullMetrics(nodeName: string) {
  const res = await fetch(`${API_BASE}/api/v1/full-metrics/${nodeName}`, {
    headers: buildHeaders(),
  });
  if (!res.ok) throw new Error(`fetchNodeFullMetrics failed: ${res.status}`);
  return res.json();
}
```

## 11. 權限邊界

整合者不需要也不應取得下列權限：

- master 主機登入權
- Tailscale 全網段橫向連線權
- Kubernetes 管理權
- metrics backend 直接查詢權
- repo 寫入權限

如需新增欄位或調整 raw JSON 結構，請由系統提供者修改後端。

## 12. 問題排查

若回傳 `401 Unauthorized`：

- 確認 token 是否正確
- 確認 request header 是否有帶上

若回傳 `404`：

- 確認 API path 是否正確
- 確認 `node_name` 是否存在

若回傳 `payload.collector_status = error`：

- 視為該節點暫時無法採集
- 前端應顯示節點資料缺口或來源異常狀態
