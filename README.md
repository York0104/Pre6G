# External Handoff Package

> [!WARNING]
> 此 branch 是舊版 Kubernetes external handoff 的歷史快照，已停止維護。
> 現行 K3s 重建、開發與部署文件請參考 [`main`](https://github.com/York0104/Pre6G/tree/main) branch。

這是目前唯一需要交付的總資料夾。

## 內容

| 路徑 | 說明 |
| --- | --- |
| `k3s-migration-bundle-sanitized/` | GitHub-safe 的 k3s migration/reference bundle，包含 Kubernetes、Helm、monitoring、GPU、RFSoC、AP、thermal YOLO 參考。 |
| `autoscale-source-split/` | 從 `/home/iccls2/AutoScale` 整理出的 source-level 分層，包含監控層、實驗層、API/dashboard 共用層。 |
| `current-lab-handoff-private/` | 私密 current-lab connection handoff，包含 kubeconfig、SSH keys、AutoScale API env 等。 |
| `MANIFEST.txt` | 總檔案清單。 |

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

`current-lab-handoff-private/` 含 kubeconfig、SSH keys、API env，不要 commit 或上傳 GitHub；請改用加密壓縮檔或其他可信任私密管道交付。

## 尚未包含

| 項目 | 原因 |
| --- | --- |
| `local/yolo26n:0.5` image tar | 此主機找不到 image tar；新 worker 需自行 build/import 或改用 registry image。 |
| worker-side `gpu-tempctl-lab` | 專案位於 worker node，不在此主機；請參考 `k3s-migration-bundle-sanitized/external-worker/`。 |
