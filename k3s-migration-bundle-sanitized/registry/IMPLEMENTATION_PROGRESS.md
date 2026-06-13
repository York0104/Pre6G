# Registry Implementation Progress

最後更新：2026-06-13

## 目標

在 repo 內建立第一版 Harbor registry workflow，讓後續重建能從「手動 build/import local image」逐步過渡到「registry build/push/pull」。

## 目前狀態

| 項目 | 狀態 | 說明 |
| --- | --- | --- |
| `registry/` 文件骨架 | 完成 | 已新增重建 SOP、驗證速查、Harbor policy 與實作追蹤文件。 |
| Harbor / k3s 設定樣板 | 完成 | 已新增 `harbor-registries.yaml.example`、secret 樣板、namespace 樣板。 |
| Kaniko full build job 樣板 | 完成 | 已升級 `kaniko-yolo26-build-job.yaml` 為 `HTTPS:8088 + Harbor CA + REPLACE_IMAGE_TAG + hostAliases` 的 full-build validation 樣板。 |
| Kaniko split build job 樣板 | 完成 | 已新增 `kaniko-yolo26-base-build-job.yaml` 與 `kaniko-yolo26-app-build-job.yaml`，作為 base/app split 正式主線。 |
| YOLO split Dockerfiles | 完成 | 已新增 `Dockerfile.base` 與 `Dockerfile.app`，保留 CUDA 成功路線，將 full build 降級為 validation path。 |
| source-level registry manifests | 完成 | 已新增 `autoscale-source-split/02-experiment-layer/yolo26_workload/*.registry.yaml`。 |
| bundle-level registry manifests | 完成 | 已新增 `k3s-migration-bundle-sanitized/thermal-yolo/yolo26_workload/*.registry.yaml`。 |
| YOLO 正式版本口徑 | 完成 | 已將目前正式支援與重建流程統一為 `0.1`。 |
| YOLO canonical path 收斂 | 完成 | 已統一以 `yolo26_workload/` 為正式路徑，並刪除舊 `yolo26_k8s/` 目錄副本。 |
| YOLO 舊命名腳本收斂 | 完成 | 已將 `run_yolo26_k8s_*` 重新命名為 `run_yolo26_workload_*`，並完成 repo 內依賴掃描與引用更新。 |
| 主 README / bundle README 串接 | 完成 | 已補上 registry 路徑與 rebuild 指引入口。 |
| Harbor 專案、robot account、CA | 完成 | `pre6g` project、push/pull robot accounts、自簽 Harbor CA 已建立。 |
| 實際 build + push | 完成 | `harbor.iccl.local:8088/pre6g/yolo26n:0.1` 已成功 build/tag/push。 |
| 實際 pull + deploy | 完成 | `icclz1` 已成功使用 Harbor image，registry 版三實例已 `Running`。 |
| Harbor HTTPS 8088 cutover | 完成 | 已確認本環境需以 `HTTPS:8088 + CA` 收斂，HTTP 路徑不再列為正式做法。 |
| `crictl pull` 自動 auth | 部分完成 | `k3s ctr --user ... pull` 已成功，`crictl pull` 仍有 `no basic auth credentials` 殘餘問題。 |
| Kaniko rebuild 文檔 | 完成 | 已改寫 `docs/rebuild/kaniko-yolo26-build-rebuild.md`，將正式主線收斂為 split pipeline，並保留 full build validation path。 |
| Kaniko full-build live validation | 部分完成 | 2026-06-13 full build 已成功通過 clone / DNS / auth / TLS / Dockerfile path，主要瓶頸已收斂為 heavy full-image build/upload。 |
| Kaniko split-build live validation | 部分完成 | 舊版 `git context + context-sub-path + Dockerfile.base/app` 已確認會卡在 Dockerfile path resolution；現已改為 `initContainer clone + dir:// context`，待重跑新一輪 live validation。 |

## 已知風險與待決策

1. 正式支援版本已統一為 `0.1`，但 `intent-lab` 的歷史 / 匯出快照仍可見 `0.5`。
2. Kaniko 適合 PoC 與受控 app-layer builder，但不建議被視為長期唯一方案。
3. 三實例 manifest 仍依賴 `hostPort` 與 `nodeSelector`，未來若做 scheduler 重構，還需再拆一次。
4. `Dockerfile.base` 目前仍會在 build 階段下載 YOLO model，正式交付時最好補上內部 artifact 管理或 checksum 驗證。
5. `icclz1` 上 `crictl pull` 的自動 Harbor auth 行為仍需後續追查；目前已以 `k3s ctr images pull --user ...` 作為有效 fallback。
6. split pipeline 的舊 blocker 已明確收斂為 `git context + context-sub-path + custom Dockerfile filename` 下的 Kaniko Dockerfile path resolution；新版已改採 `initContainer clone + dir:// context`。

## 建議下一步

1. 將 Harbor `push` / `pull` token rotate，因本輪除錯過程中曾短暫暴露在終端貼文中。
2. 若要完全收斂 runtime pull 體驗，繼續追 `crictl pull` 的自動 auth 問題。
3. 若要正式交付，將 `harbor-ca.crt`、`registries.yaml` 與 node-side trust 安裝整理成可重複使用的主機 bootstrap 腳本。
4. 以新版 `initContainer clone + dir:// context` 重新驗證 `kaniko-yolo26-base-build-job.yaml`。
5. base image 成功後，再驗證 `kaniko-yolo26-app-build-job.yaml` 與 `intent-lab` rollout 閉環。

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
