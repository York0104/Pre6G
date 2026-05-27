# 02 Experiment Layer

本層保存 thermal YOLO 實驗 workflow。它依賴 `01-monitoring-layer` 提供 metrics/API，但監控層不依賴本層。

## 目前環境狀態

目前 `icclz1` 已是新的 k3s GPU worker，並可正常提供：

- `node-exporter`
- `vmagent-node-local`
- `Netdata child`
- `nvidia-device-plugin`
- `dcgm-exporter`
- `nvidia.com/gpu=1`
- `nvidia.com/gpu.shared=4`（目前 `icclz1` 已啟用 time-slicing，可供三實例 YOLO/shared-GPU workflow 使用）

因此 `02-experiment-layer` 已對齊目前環境的節點名稱、監控入口與 worker SSH 位置：

- worker node: `icclz1`
- worker host/IP: `140.113.179.6`
- worker external repo: `/home/icclz1/gpu-tempctl-lab`
- VictoriaMetrics: `http://140.113.179.9:31888`
- Netdata: `http://140.113.179.9:32163`

## 重現前提

### 1. 單 pod 實驗

單 pod 實驗可直接沿用目前 cluster，但需先把 YOLO image 建好並匯入 k3s：

```bash
cd autoscale-source-split/02-experiment-layer/yolo26_k8s
bash build_and_import_image_to_k3s.sh
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
```

主要 image tag：

- `local/yolo26n:0.1`
- `local/yolo26n:0.5`

### 2. 多 pod saturation / 3-instance 實驗

這類實驗使用 `nvidia.com/gpu.shared`。目前 `icclz1` 已完成 time-slicing，現場狀態為：

- `nvidia.com/gpu.shared: 4`
- `yolo26n-focus` / `yolo26n-bg-1` / `yolo26n-bg-2` 可在 `intent-lab` 正常 `Running`
- `18081` / `18082` / `18083` 的 `healthz` 已驗證可回 `200`

本目錄已放入目前可用的 reference config：

- `experiments_yolo/saturation_multi_pod/gpu-sharing-icclz1.yaml`

完整背景與舊 bundle 參考見：

- `k3s-migration-bundle-sanitized/nvidia-device-plugin/`

實作注意：

- 三實例 manifest 使用 `hostPort`，因此 rollout strategy 應使用 `Recreate`，避免 rolling update 時留下因 port 衝突而長期 `Pending` 的 pod
- 若未來在另一台 GPU worker 重建，除了 image 匯入外，也要一併確認該節點的 `nvidia.com/gpu.shared` 已出現

## 主要用途

- 部署 YOLO26 k3s workload。
- 產生 inference traffic 並記錄 latency。
- 透過 worker 端 `gpu-tempctl-lab` 控制 fan/thermal cycle。
- 收集 `vm_aggregator.py` metrics，合併 latency、thermal phase 與 GPU/Node 指標。
- 產生實驗 summary、dataset 與圖表。

## 根目錄檔案與目錄

| 路徑 | 說明 |
| --- | --- |
| `DEPENDENCY_TRACE.md` | 說明本層未依賴舊 `experiments/load_injection/`、`model_load/`、`monitoring/`，並追蹤 fan/load 來源。 |
| `experiments_yolo/` | 目前主要 YOLO 實驗 workflow，包含 saturation、single pod、fault fan、bgload fan cycle。 |
| `scripts/` | 較早期或通用的 YOLO26 thermal/rate sweep 腳本。 |
| `thermal_analysis/` | thermal YOLO 資料收集、合併、繪圖與 batch runner。 |
| `yolo26_k8s/` | YOLO26 inference service Dockerfile、app、k8s manifests、image build/import helper。 |

## Smoke Test 狀態

2026-05-28 已完成短版 baseline smoke test：

- focus: `50/50` success，client mean `137.589 ms`，server mean `18.783 ms`
- bg-1: `25/25` success，client mean `181.229 ms`，server mean `22.813 ms`
- bg-2: `25/25` success，client mean `221.967 ms`，server mean `22.610 ms`
- `healthz` 監看與 warmup 皆正常

測試輸出已驗證後刪除；如需重跑，可直接使用 `scripts/run_A_normal_baseline_yolo.sh`，並建議將 `OUTDIR` 指到 `/tmp` 或專案內暫存目錄。
