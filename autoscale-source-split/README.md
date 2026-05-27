# AutoScale Source Split

本資料夾是從 `/home/icclz2/Pre6G` 整理出的 source-level 交接版本，用於讓接手者不必先理解整個歷史 repo，就能重建目前需要的監控、實驗與 API/UI。

## 分層原則

```text
01-monitoring-layer/        監控與 metrics 聚合
02-experiment-layer/        thermal YOLO 實驗
03-shared-api-dashboard/    AutoScale API 與 dashboard
99-not-included-reference/  未納入項目說明
```

允許的依賴方向：

```text
02-experiment-layer -> 01-monitoring-layer metrics/API
03-shared-api-dashboard -> 01-monitoring-layer 與 02-experiment-layer
```

監控層不應依賴 YOLO 或 thermal experiment runner。API/dashboard 因同時服務監控與實驗控制，因此獨立成第三層。

## 目錄說明

| 路徑 | 說明 |
| --- | --- |
| `01-monitoring-layer/` | VictoriaMetrics、Netdata、DCGM、AP、RFSoC、Kubernetes metrics aggregator 與監控部署參考。 |
| `02-experiment-layer/` | YOLO26 workload、thermal/fan-cycle 實驗腳本、latency client、資料合併與繪圖工具。 |
| `03-shared-api-dashboard/` | `autoscale_api/`、前端 dashboard source、共用 Python requirements。 |
| `99-not-included-reference/` | 說明哪些原始 AutoScale 檔案未納入，以及排除原因。 |

## 未納入原則

未納入 `__pycache__/`、`*.pyc`、`node_modules/`、`dist/`、virtualenv、歷史結果、備份檔與真實 `.env`。私密 runtime 值保留在：

```text
../current-lab-handoff-private/private-files-to-fill/
```

## 接手建議

1. 先看 `../MONITORING_REBUILD_SOP.md`，照正式 `k3s` 重建順序部署監控。
2. 再看 `01-monitoring-layer/README.md` 與 `03-shared-api-dashboard/README.md`，啟動 API/UI。
3. `02-experiment-layer/README.md` 雖尚未列入本次 `k3s` 重建驗收，但必要 source/workload 已保留，可在下一台 `k3s` 環境接續完成實驗層。
