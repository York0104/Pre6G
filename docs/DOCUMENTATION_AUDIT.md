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

## Repository Roles

| 路徑 | 角色 | 維護規則 |
| --- | --- | --- |
| `monitoring-rebuild/` | Canonical monitoring rebuild manifests | 依 `MONITORING_REBUILD_SOP.md` 使用與修改。 |
| `autoscale-source-split/` | Canonical source-level code、API/dashboard 與 experiment 定義 | 功能與部署文件以程式、manifest 與 component README 交叉驗證。 |
| `config/` | Public/private configuration entry layer | 多數項目是 symlink；須修改其 canonical destination，而非建立第二份副本。 |
| `k3s-migration-bundle-sanitized/` | Migration/reference snapshot | 保留作為可攜交付與 recovery reference；不可雙向同步，分歧需先比對 canonical source。 |
| `shareable-bundles/` | 可單獨交付工具 | 僅涵蓋其子工具的依賴與操作，不取代完整 source tree。 |
| 日期化 `results/`、`PROGRESS`、`STATUS`、`MANIFEST` | Historical evidence / transitional snapshot | 保留研究與交付證據；不得當作目前 runtime 或 canonical parameter 定義。 |

## Dependency Sources

| 範圍 | Canonical dependency source | 備註 |
| --- | --- | --- |
| AutoScale API | `03-shared-api-dashboard/requirements.txt` | Dockerfile 使用同一份 pinned requirements。 |
| YOLO inference container | `02-experiment-layer/yolo26_workload/requirements.txt` + Dockerfile CUDA/PyTorch install | 不與分析工具依賴混用。 |
| Offline analysis / plotting / training | `02-experiment-layer/requirements-analysis.txt` | 選用；版本記錄為本機 `iccl` 已觀察環境，非對 runtime 的保證。 |
| Dashboard | `cluster-dashboard/package.json` + `package-lock.json` | Node.js engine 由 `package.json` root metadata 宣告。 |

## Transitional And Duplicate Content

| Path / group | Current role | Canonical replacement | Recommended action | Risk / evidence |
| --- | --- | --- | --- | --- |
| `config/manifests/monitoring/` | symlink entry layer | `monitoring-rebuild/` | KEEP_AND_CLARIFY | 11 common YAML targets are byte-identical; do not create a second copy. |
| `config/manifests/experiment/` | symlink entry layer | `autoscale-source-split/02-experiment-layer/` | KEEP_AND_CLARIFY | Entry paths are intentional operator shortcuts. |
| `k3s-migration-bundle-sanitized/thermal-yolo/` | portable migration snapshot | `autoscale-source-split/02-experiment-layer/` | KEEP_AND_CLARIFY | Some files match exactly, while workload, runner and experiment files differ; it is not safe to delete or auto-sync. |
| `k3s-migration-bundle-sanitized/netdata-ap/` | portable AP/Netdata reference | `autoscale-source-split/01-monitoring-layer/` | KEEP_AND_CLARIFY | AP scripts and README differ from source; compare before applying. |
| `*.current.yaml`, `*.backup.yaml`, `*.before.yaml`, `*.new.yaml` in migration bundle | captured transition/reference states | current canonical manifests or verified live export | MARK_DEPRECATED | These names are not a proof of recency. Select only after manifest and cluster validation. |
| Root and bundle `MANIFEST.txt` | historical handoff snapshot | `git ls-files` | KEEP_AND_CLARIFY | They are not complete inventories of the current tracked tree. |
| Date-stamped `results/`, `PROGRESS`, `STATUS` documents | experiment / delivery evidence | none | KEEP | Do not delete or rewrite methodology/KPI claims without a separate evidence review. |

## Environment Boundaries

- The repo-local `iccl` interpreter observed during this audit is Python `3.10.12`; the AutoScale API container uses Python `3.12-slim`. There is no single host-Python guarantee for every experiment script.
- The dashboard lockfile and `package.json` require Node.js `^20.19.0 || >=22.12.0`; the Docker build uses Node `22`.
- `config/private-runtime/` is a local symlink entry layer to `~/pre6g-private/`. Its live targets are intentionally not Git-tracked. Their presence and permissions are `UNVERIFIED` after a fresh clone.
- Machine-specific `/home/icclz2/...` and `/home/icclz1/...` paths in dated operations and experiment documents are reference deployment paths, not portable defaults unless the document explicitly says otherwise.

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
