# Registry Implementation Progress

最後更新：2026-05-31

## 目標

在 repo 內建立第一版 Harbor registry workflow，讓後續重建能從「手動 build/import local image」逐步過渡到「registry build/push/pull」。

## 目前狀態

| 項目 | 狀態 | 說明 |
| --- | --- | --- |
| `registry/` 文件骨架 | 完成 | 已新增重建 SOP、驗證速查、Harbor policy 與實作追蹤文件。 |
| Harbor / k3s 設定樣板 | 完成 | 已新增 `harbor-registries.yaml.example`、secret 樣板、namespace 樣板。 |
| Kaniko build job 樣板 | 完成 | 已新增 `kaniko-yolo26-build-job.yaml`，預設以 YOLO26 workload 為第一個 PoC。 |
| source-level registry manifests | 完成 | 已新增 `autoscale-source-split/02-experiment-layer/yolo26_workload/*.registry.yaml`。 |
| bundle-level registry manifests | 完成 | 已新增 `k3s-migration-bundle-sanitized/thermal-yolo/yolo26_workload/*.registry.yaml`。 |
| YOLO 正式版本口徑 | 完成 | 已將目前正式支援與重建流程統一為 `0.1`。 |
| YOLO canonical path 收斂 | 完成 | 已統一以 `yolo26_workload/` 為正式路徑，並刪除舊 `yolo26_k8s/` 目錄副本。 |
| YOLO 舊命名腳本收斂 | 完成 | 已將 `run_yolo26_k8s_*` 重新命名為 `run_yolo26_workload_*`，並完成 repo 內依賴掃描與引用更新。 |
| 主 README / bundle README 串接 | 完成 | 已補上 registry 路徑與 rebuild 指引入口。 |
| Harbor 專案、robot account、CA | 待實作 | 需在實際 lab / 交付環境建立。 |
| 實際 build + push | 待驗證 | 尚未在 cluster 內執行 Kaniko job。 |
| 實際 pull + deploy | 待驗證 | 尚未在目標 k3s node 以 Harbor image 完整驗證。 |

## 已知風險與待決策

1. 正式支援版本已統一為 `0.1`，但 `intent-lab` 的歷史 / 匯出快照仍可見 `0.5`。
2. Kaniko 適合 PoC，但不建議被視為長期唯一方案。
3. 三實例 manifest 仍依賴 `hostPort` 與 `nodeSelector`，未來若做 scheduler 重構，還需再拆一次。
4. Dockerfile 在 build 階段會下載 YOLO model，正式交付時最好補上內部 artifact 管理或 checksum 驗證。

## 建議下一步

1. 在 Harbor 建立 `pre6g` project 與 pull/push robot account。
2. 先建立 `harbor.iccl.local/pre6g/yolo26n:0.1`。
3. 依 `REBUILD_STEPS.md` 在每個 k3s node 配置 `registries.yaml`。
4. 先手動 build/push 一版 image 驗證整條 pull path。
5. pull path 穩定後，再套用 `kaniko-yolo26-build-job.yaml` 驗證 cluster-side build。

## 驗證結果紀錄欄位

後續每次驗證建議至少補記：

- 驗證日期
- Harbor image tag
- Harbor digest
- 使用的 manifest 路徑
- 成功 pull 的 node 名稱
- `kubectl rollout status` 結果
- `/healthz` 驗證結果
- 任何與 GPU、TLS、auth、DNS 相關的錯誤
