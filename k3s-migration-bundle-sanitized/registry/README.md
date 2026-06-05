# Pre6G Registry Workflow

本資料夾收斂 Pre6G 在 k3s rebuild 階段的 image registry 樣板、Harbor/Kaniko 參考設定，以及後續追蹤與重建文件。

## 目標

- 保留既有 `local/yolo26n:*` 的單機實驗路徑。
- 新增 Harbor registry image 路徑，減少新 worker 手動 build/import 成本。
- 先以 YOLO26 workload 完成第一波可重建樣板。
- 將 image build、pull、部署、驗證步驟整理成 repo 內可追蹤文件。

## 目前內容

| 路徑 | 說明 |
| --- | --- |
| `IMPLEMENTATION_PROGRESS.md` | 目前已完成項目、待辦、風險與下一步。 |
| `REBUILD_STEPS.md` | Harbor 路徑的實作與重建 SOP。 |
| `VERIFY_REGISTRY_PULL.md` | 針對 k3s/containerd 拉 Harbor image 的驗證與除錯速查。 |
| `harbor-registries.yaml.example` | `/etc/rancher/k3s/registries.yaml` 樣板。 |
| `imagepullsecret.example.yaml` | `image-build` 與 `intent-lab` namespace 的 secret 範例。 |
| `image-build.namespace.yaml` | Kaniko build job 專用 namespace。 |
| `kaniko-yolo26-build-job.yaml` | YOLO26 build job 範例。 |
| `harbor-project-policy.md` | repository/tag/digest 命名建議。 |

## Canonical Manifests

目前 bundle 內唯一正式使用：

- `../thermal-yolo/yolo26_workload/deployment.registry.yaml`
- `../thermal-yolo/yolo26_workload/yolo26_3inst_icclz1.registry.yaml`

## 注意事項

- 目前正式支援與重建流程已統一使用 `local/yolo26n:0.1` / `harbor.iccl.local:8088/pre6g/yolo26n:0.1`。
- 2026-06-04 實測後，Harbor 正式建議做法已收斂為 `HTTPS:8088 + 自簽 CA`，不再建議沿用舊的 `HTTP:8088` 路徑。
- `intent-lab` 的歷史匯出快照仍可見 `local/yolo26n:0.5`，請將其視為歷史狀態，不要當作新的 rebuild 標準。
- registry化能解決 image 分發問題，但 `hostPort`、`nodeSelector` 仍會限制三實例 workload 的調度彈性。
- Kaniko 倉庫已於 2025-06-03 archived；目前保留為 PoC/實驗用 builder 樣板，長期可改為 BuildKit、Buildah、Tekton 或 CI runner。
