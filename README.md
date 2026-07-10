# External Handoff Package

這是目前唯一需要交付的總資料夾。

## K3s Rebuild Entry

本 repo 目前的正式交付主線是 `k3s` 重建版。

- 先看 [MONITORING_REBUILD_SOP.md](MONITORING_REBUILD_SOP.md)
- 再看 [monitoring-rebuild/REBUILD_PARAMETERS.md](monitoring-rebuild/REBUILD_PARAMETERS.md)
- 文件、程式與部署檔的權威來源請看 [docs/DOCUMENTATION_AUDIT.md](docs/DOCUMENTATION_AUDIT.md)
- `02-experiment-layer` 目前仍是後續工作，不列入本次 `k3s` 主線交付驗收

## 內容

| 路徑 | 說明 |
| --- | --- |
| `k3s-migration-bundle-sanitized/` | GitHub-safe 的 k3s migration/reference bundle，包含 Kubernetes、Helm、monitoring、GPU、RFSoC、AP、thermal YOLO 與 registry rebuild 參考。 |
| `autoscale-source-split/` | 從 `/home/icclz2/Pre6G` 整理出的 source-level 分層，包含監控層、實驗層、API/dashboard 共用層。 |
| `MANIFEST.txt` | 歷史交付快照的檔案清單；目前追蹤內容請以 `git ls-files` 為準。 |

## Repo 上傳注意事項

若將此資料夾初始化成 Git repo，`.gitignore` 已排除：

```text
current-lab-handoff-private/
```

建議 repo 只包含：

```text
k3s-migration-bundle-sanitized/
autoscale-source-split/
README.md
MANIFEST.txt
.gitignore
```

`current-lab-handoff-private/` 是刻意不納入本 repo 的私密 handoff 目錄；目前 checkout 不包含該資料夾。它應包含 kubeconfig、SSH keys、API env 等敏感資料，請以加密壓縮檔或其他可信任私密管道交付，勿 commit 或上傳 GitHub。

## 尚未包含

| 項目 | 原因 |
| --- | --- |
| Harbor 實際 credentials / CA / built image | repo 已新增 `k3s-migration-bundle-sanitized/registry/` 樣板與 registry manifests，但正式 Harbor token、CA 與已建好的 image 仍屬 private runtime 資料。 |
| `local/yolo26n:0.1` image tar | 此主機找不到 image tar；若不走 Harbor 路徑，新 worker 仍需自行 build/import。 |
| worker-side `gpu-tempctl-lab` | 專案位於 worker node，不在此主機；請參考 `k3s-migration-bundle-sanitized/external-worker/`。 |
