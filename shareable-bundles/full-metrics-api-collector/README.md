# Full Metrics API Collector Bundle

這是一份可獨立交給外部整合者的最小監控資料收集包。

## 交付內容

正式交付時，除了本 bundle 本身，還需要另外提供：

- `AUTOSCALE_API_BASE`
- `AUTOSCALE_API_TOKEN`，若 API 已啟用驗證

也就是說，實際可運作交付至少包含：

1. `full-metrics-api-collector.tar.gz`
2. 一組可用的 API 設定資訊

建議以安全管道另外提供：

```env
AUTOSCALE_API_BASE=http://140.113.179.9:8000
AUTOSCALE_API_TOKEN=replace-with-issued-token
```

若對方使用 OpenWrt，建議另外提醒：

```env
OUTPUT_ROOT=/tmp/node_metric_csv_logs
PYTHON_BIN=python3
```

## 用途

本工具透過 `AutoScale API` 週期性讀取 `/api/v1/full-metrics`，並將所有節點監控資料落地為 CSV 與 JSONL。

目前 K8s node 的 GPU 摘要欄位已改成較清楚的語意：

- `cluster_semantic.gpu.physical_count`
- `cluster_semantic.gpu.standard_allocatable`
- `cluster_semantic.gpu.shared_allocatable`
- `cluster_semantic.gpu.mode`
- `target_node_semantic.gpu.physical_count`
- `target_node_semantic.gpu.standard_allocatable`
- `target_node_semantic.gpu.shared_allocatable`
- `target_node_semantic.gpu.mode`

若使用 CSV，bundle 也會另外保留 `gpu.mode` 與相關 `status` 文字欄位，方便人工判讀。

外部整合者只需要：

- `AUTOSCALE_API_BASE`
- `AUTOSCALE_API_TOKEN`，若 API 啟用驗證

不需要：

- Kubernetes kubeconfig
- cluster SSH 權限
- VictoriaMetrics / Netdata 直接存取權限
- RFSoC SSH 權限
- OpenWrt AP gateway SSH 權限

---

## Bundle 內容

```text
full-metrics-api-collector/
├── README.md
├── collect_full_metrics_api_csv_standalone.py
├── run_full_metrics_api_collector.sh
├── .env.example
└── requirements.txt
```

---

## 支援的資料來源

本 collector 只讀取：

```text
GET /api/v1/full-metrics
```

因此會收集 AutoScale API server 端已納入 `full-metrics` 的節點資料，例如：

- 一般 `k3s` nodes
- `RFSoC`：`rfsoc4x2-pynq`
- `AP gateway`：`openwrt_ap`

前提是 AutoScale API server 端已經將這些節點納入 `/api/v1/full-metrics` 回應。

---

## 建議執行環境

建議使用：

- Ubuntu
- Debian
- 一般 Linux host
- Python 3.8+

不建議在 OpenWrt / embedded AP 上長時間執行 collector。

原因：

- OpenWrt 儲存空間通常較小
- 長時間寫入 CSV / JSONL 可能增加 flash 寫入負擔
- OpenWrt 的 Python 環境可能沒有完整 `venv` / `pip` / `ensurepip`
- OpenWrt 適合做短時間連線測試，不建議作為正式資料落地主機

若只是在 OpenWrt 上短時間測試，請將 `OUTPUT_ROOT` 設為 `/tmp/node_metric_csv_logs`。

---

## 使用方式

### 1. 確認 Python 3

```bash
python3 --version
```

若在 Ubuntu / Debian 上，可選擇建立 venv：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

若在 OpenWrt 上，不建議建立 venv。請直接使用系統的 `python3`。

---

### 2. 建立 `.env`

```bash
cp .env.example .env
```

編輯 `.env`：

```env
AUTOSCALE_API_BASE=http://140.113.179.9:8000
AUTOSCALE_API_TOKEN=
INTERVAL_SECONDS=30
OUTPUT_ROOT=$HOME/node_metric_csv_logs
REQUEST_TIMEOUT_SECONDS=30
PYTHON_BIN=python3
```

若 API 啟用 token，請填入：

```env
AUTOSCALE_API_TOKEN=replace-with-issued-token
```

若在 OpenWrt 上短時間測試，建議改成：

```env
OUTPUT_ROOT=/tmp/node_metric_csv_logs
PYTHON_BIN=python3
```

---

### 3. 載入 `.env`

```bash
set -a
. ./.env
set +a
```

確認變數：

```bash
echo "$AUTOSCALE_API_BASE"
echo "$OUTPUT_ROOT"
echo "$PYTHON_BIN"
```

---

### 4. 驗證 API root

若 API 需要 token：

```bash
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" \
"$AUTOSCALE_API_BASE/"
```

若 API 不需要 token：

```bash
curl "$AUTOSCALE_API_BASE/"
```

正常應回傳類似：

```json
{"message":"Pre6G AutoScale API is running"}
```

---

### 5. 驗證 full-metrics

若 API 需要 token：

```bash
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" \
"$AUTOSCALE_API_BASE/api/v1/full-metrics"
```

若系統有 `jq`，可查看摘要：

```bash
curl -s -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" \
"$AUTOSCALE_API_BASE/api/v1/full-metrics" \
| jq "{schema, count, ok_count, error_count}"
```

理想狀態為：

```text
ok_count 接近 count
```

若 server 端有已知異常節點，`error_count` 可能大於 0。collector 會照實記錄這些 error payload。

---

### 6. 啟動 collector

一般 Linux 環境可使用 wrapper：

```bash
sh run_full_metrics_api_collector.sh
```

或：

```bash
bash run_full_metrics_api_collector.sh
```

若要直接執行：

```bash
python3 collect_full_metrics_api_csv_standalone.py
```

停止方式：

```text
Ctrl+C
```

---

## 輸出內容

每次啟動都會建立一個新目錄：

```text
$OUTPUT_ROOT/YYYYMMDD_HHMMSS/
```

裡面包含：

- 每個節點各自一份 CSV
- 每個節點各自一份 raw JSONL
- 完整 API 回應：`raw_json/full_metrics_response.jsonl`
- `collector.log`
- `nodes_manifest.json`

範例：

```text
$OUTPUT_ROOT/20260604_120000/
├── ap_gateway_openwrt_ap.csv
├── k8s_icclz1.csv
├── k8s_icclz2.csv
├── rfsoc_rfsoc4x2-pynq.csv
├── collector.log
├── nodes_manifest.json
└── raw_json/
    ├── ap_gateway_openwrt_ap.jsonl
    ├── full_metrics_response.jsonl
    ├── k8s_icclz1.jsonl
    ├── k8s_icclz2.jsonl
    └── rfsoc_rfsoc4x2-pynq.jsonl
```

---

## 檢查輸出

列出所有輸出檔案：

```bash
find "$OUTPUT_ROOT" -type f | sort
```

查看 CSV 前幾列：

```bash
for f in "$OUTPUT_ROOT"/*/*.csv; do
  echo "===== $f ====="
  head -n 3 "$f"
done
```

查看完整 API raw JSONL 筆數：

```bash
wc -l "$OUTPUT_ROOT"/*/raw_json/full_metrics_response.jsonl
```

查看最後一筆 full-metrics 回應：

```bash
tail -n 1 "$OUTPUT_ROOT"/*/raw_json/full_metrics_response.jsonl
```

---

## 已知問題

若 AutoScale API server 端本身已有已知異常節點，`/api/v1/full-metrics` 可能會回傳：

```text
collector_status=error
```

collector 不會修復 server 端問題，但會將該節點的 error payload 照實記錄到對應 CSV 與 JSONL。

若對外交付時希望 `error_count=0`，建議由 AutoScale API server 提供者先修復上游監控，或暫時排除異常節點。

---

## 注意事項

- 本工具只讀取 AutoScale API，不會修改 cluster。
- 本工具不需要 kubeconfig。
- 本工具不需要 SSH 到 cluster、RFSoC 或 OpenWrt AP。
- 本工具不需要直接存取 VictoriaMetrics / Netdata。
- 若 API token 未啟用，可留空 `AUTOSCALE_API_TOKEN`。
- 若 API 已啟用驗證，必須提供有效 token。
- 若 `/api/v1/full-metrics` 在 server 端已經包含 `collector_status=error` 的節點，本 collector 會照實記錄，不會自動修復。
- 若只是查看即時狀態，可使用 dashboard；若需要落地 CSV / JSONL，則使用本 collector。

---

## 安全建議

請勿交付以下內容給外部整合者：

- master SSH 帳密
- Kubernetes kubeconfig
- VictoriaMetrics / Netdata 直接存取權限
- RFSoC SSH 帳密
- OpenWrt AP SSH 帳密
- server 端 systemd env 原始檔
- 內部正式 API token

建議為外部整合者建立專用 read-only API token。若 token 已曝光，請更換 token 後再正式交付。
