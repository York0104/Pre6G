# Separation Audit

本資料夾說明 AutoScale 交接時的監控/實驗分離邊界、檔案分類與舊版清理判斷。

## 文件

| 文件 | 說明 |
| --- | --- |
| `MONITORING_EXPERIMENT_SEPARATION.md` | 定義 monitoring layer 與 experiment layer 的邊界、允許依賴與重建順序。 |
| `AUTOSCALE_FILE_GROUPS.md` | 將 AutoScale 重要檔案分成 monitoring、experiment、API/dashboard、legacy/reference。 |
| `LEGACY_CLEANUP_CANDIDATES.md` | 列出備份、demo、歷史研究線與不建議納入交接的內容。 |
| `HOME_YAML_AUDIT.md` | 檢查 `/home/iccls2` 根目錄 YAML/CSV 是否已納入、被新版覆蓋或刻意排除。 |

## 結論

監控與實驗可在部署與程式責任上分離：

```text
experiments -> monitoring metrics/API
```

反向依賴不應存在：

```text
monitoring -> experiments
```

AutoScale API 同時有 monitoring endpoints 與 experiment-control endpoints，因此在 source split 中獨立為 `03-shared-api-dashboard/`。
