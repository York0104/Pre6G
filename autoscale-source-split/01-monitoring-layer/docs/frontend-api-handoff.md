# Frontend API Handoff

本文件提供給前端整合者，說明如何安全接入 Pre6G AutoScale 監控資料。

## 1. 目的

前端網站只需讀取 AutoScale 提供的唯讀 API，不需要直接存取：

- master SSH
- Kubernetes kubeconfig
- VictoriaMetrics
- Netdata
- RFSoC SSH

建議整合方式為：

```text
Frontend
  -> AutoScale API
  -> /api/v1/nodes
  -> /api/v1/nodes/status
  -> /api/v1/nodes/{node_name}/status
```

如果前端需要所有節點的完整 raw JSON，請改看
[`docs/full-metrics-handoff.md`](/home/icclz2/Pre6G/docs/full-metrics-handoff.md)。

## 2. 你會收到什麼

系統提供者會提供：

- `API_BASE_URL`
- 可查詢的 node 名稱
- 是否啟用 API token
- 若有啟用 token，會另外提供 token 值

範例：

```env
VITE_AUTOSCALE_API_BASE=http://100.x.y.z:8000
```

如果啟用 token：

```env
VITE_AUTOSCALE_API_TOKEN=replace-with-issued-token
```

## 3. 可用 API

### `GET /`

用途：

- 健康檢查
- 確認 API 是否在線

### `GET /api/v1/nodes`

用途：

- 取得固定節點 inventory
- 取得 node 名稱、IP、CPU、memory、GPU 基本資訊

### `GET /api/v1/nodes/status`

用途：

- 取得全部節點的即時狀態
- 建議前端總覽頁使用這個端點

### `GET /api/v1/nodes/{node_name}/status`

用途：

- 取得單一節點即時狀態
- 建議詳細頁使用這個端點

## 4. 建議輪詢頻率

- 總覽頁：每 `3-5` 秒輪詢一次
- 單節點詳細頁：每 `1-3` 秒輪詢一次
- 若只是靜態資訊頁，可只在頁面載入時呼叫一次 `/api/v1/nodes`

不建議前端以 `1s` 以下頻率密集輪詢全部節點。

## 5. 認證方式

如果 API token 未啟用，直接呼叫即可。

如果 API token 已啟用，請在每次 request 帶其中一種 header：

```http
Authorization: Bearer <token>
```

或：

```http
X-API-Token: <token>
```

## 6. JavaScript 範例

```ts
const API_BASE = import.meta.env.VITE_AUTOSCALE_API_BASE;
const API_TOKEN = import.meta.env.VITE_AUTOSCALE_API_TOKEN;

function buildHeaders(): HeadersInit {
  if (!API_TOKEN) return {};
  return {
    Authorization: `Bearer ${API_TOKEN}`,
  };
}

export async function fetchNodeList() {
  const res = await fetch(`${API_BASE}/api/v1/nodes`, {
    headers: buildHeaders(),
  });
  if (!res.ok) throw new Error(`fetchNodeList failed: ${res.status}`);
  return res.json();
}

export async function fetchAllNodeStatus() {
  const res = await fetch(`${API_BASE}/api/v1/nodes/status`, {
    headers: buildHeaders(),
  });
  if (!res.ok) throw new Error(`fetchAllNodeStatus failed: ${res.status}`);
  return res.json();
}

export async function fetchNodeStatus(nodeName: string) {
  const res = await fetch(`${API_BASE}/api/v1/nodes/${nodeName}/status`, {
    headers: buildHeaders(),
  });
  if (!res.ok) throw new Error(`fetchNodeStatus failed: ${res.status}`);
  return res.json();
}
```

## 7. curl 測試

不帶 token：

```bash
curl "$API_BASE_URL/api/v1/nodes/status" | jq
```

帶 token：

```bash
curl \
  -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" \
  "$API_BASE_URL/api/v1/nodes/status" | jq
```

## 8. 權限邊界

前端整合者不需要也不應取得下列權限：

- master 主機登入權
- Tailscale 全網段橫向連線權
- Kubernetes 管理權
- metrics backend 直接查詢權
- repo 寫入權限

如需新增欄位或調整 API schema，請向系統提供者提出，由後端調整 API。

## 9. 問題排查

若回傳 `401 Unauthorized`：

- 確認 token 是否正確
- 確認 request header 是否有帶上

若回傳 `404`：

- 確認 API path 是否正確
- 確認 node 名稱是否存在

若發生 CORS 錯誤：

- 請提供前端網站實際來源網址給系統提供者
- 由後端補入 CORS allowlist
