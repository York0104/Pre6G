# Documentation Audit

本文件定義目前 repo 的文件權威來源與稽核邊界。最後一次全域一致性稽核：2026-07-10。

## Canonical Sources

| 資訊類型 | 權威來源 |
| --- | --- |
| K3s 監控重建順序 | `MONITORING_REBUILD_SOP.md` 與 `monitoring-rebuild/*.yaml` |
| 重建參數與 namespace／port | `monitoring-rebuild/REBUILD_PARAMETERS.md` 與實際 manifest |
| CLI 參數 | 各 Python `argparse` 定義與 Shell script 的 usage／預設值 |
| API path、method、request／response schema | `autoscale-source-split/03-shared-api-dashboard/autoscale_api/app/main.py`、`app/routers/`、`app/schemas/`；可用時以 `/openapi.json` 為準 |
| API runtime 環境變數 | `app/security.py`、各 service／adapter 的 `os.getenv` 與 `01-monitoring-layer/systemd/autoscale-api.env.example` |
| Kubernetes 資源 | `monitoring-rebuild/*.yaml`、`autoscale-source-split/**/manifests/` 與 `03-shared-api-dashboard/deploy/k3s/*.yaml` |
| 監控指標、query 與聚合語意 | `01-monitoring-layer/vm_aggregator.py`、`vm_agg_rfsoc.py`、`vm_agg_ap_gateway.py` 與 API adapter 實作 |
| 設備可用性公式與狀態 | `02-experiment-layer/device_availability/availability_probe.py`、`node_sentinel.py`、`analyze_r2_results.py` |
| 實驗資料欄位與輸出 | 各 experiment runner／analysis script；文件中的日期化 result 報告只描述當時量測 |
| 目前開發狀態 | 程式碼、測試與 `PROJECT_STATUS.md`；日期化進度／結果文件不是現行部署狀態 |

## Documentation Status

| 文件／目錄 | 用途 | 狀態 | 是否權威 | 備註 |
| --- | --- | --- | --- | --- |
| `README.md` | repo 入口與交付範圍 | Current | 是 | 指向目前 K3s rebuild 主線。 |
| `MONITORING_REBUILD_SOP.md` | K3s 重建操作順序 | Current | 是 | 需配合 manifest 與 parameters 文件。 |
| `monitoring-rebuild/REBUILD_PARAMETERS.md` | 監控重建參數 | Current | 是 | 實際值仍以套用前 manifest 為準。 |
| `autoscale-source-split/01-monitoring-layer/README.md` | 監控 source 層導覽 | Current | 是 | collector 行為以 Python 實作為準。 |
| `autoscale-source-split/03-shared-api-dashboard/autoscale_api/README.md` | API 操作與現場驗證紀錄 | Current with dated observations | 部分 | endpoint/schema 以 router/schema 為準；量測數據是歷史觀測。 |
| `autoscale-source-split/03-shared-api-dashboard/deploy/k3s/README.md` | API/dashboard K3s 部署樣板 | Current | 是 | hostPath 路徑屬 fallback，需 private runtime 值。 |
| `autoscale-source-split/02-experiment-layer/**/results/*.md` | 實驗結果與分析報告 | Historical | 否 | 不代表目前環境或可重現結果。 |
| `MONITORING_REBUILD_PROGRESS.md`、`LOCAL_BOOTSTRAP_STATUS.md` | 日期化進度／現場狀態 | Historical | 否 | 不可取代程式、manifest 或正式 SOP。 |
| `k3s-migration-bundle-sanitized/` | 跨 cluster 重建 reference bundle | Reference | 部分 | `*.current.yaml`／`*.backup.yaml` 必須先人工確認，不視為唯一 active manifest。 |
| `MANIFEST.txt` | 歷史交付快照清單 | Historical | 否 | 目前追蹤檔案請執行 `git ls-files`。 |

## Safe Documentation Check

在 repo root 執行：

```bash
python3 scripts/check_docs_consistency.py
```

此工具檢查 Markdown 相對連結、同文件／跨文件 heading anchor、明示的 repo-root Python／Shell 入口，以及 API/dashboard 文件提及但不存在於 FastAPI router 的 API path。它不推測 code block 的工作目錄，因此相對 command 仍應搭配文件中的 `cd` 步驟人工檢視。外部 URL 僅列出，不主動連線；需要網路或登入的連結應人工以瀏覽器確認。

## Known Limits

- 不會對 Kubernetes cluster、GPU、VictoriaMetrics、Netdata、PDU、SSH worker 或 private runtime 進行寫入或壓力測試。
- `current-lab-handoff-private/` 不在 repo 中；任何需要 kubeconfig、SSH key、token 或真實 endpoint 的步驟都需要由受授權人員提供 private runtime 設定。
- 日期化實驗結果與 benchmark 數值未在本稽核重新執行，不能視為目前正式環境結果。
