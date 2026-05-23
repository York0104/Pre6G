# NVIDIA Device Plugin

本資料夾保存 NVIDIA Device Plugin 與 GPU sharing 參考。

| 檔案 | 說明 |
| --- | --- |
| `helm-values-nvdp.current.yaml` | 來源 cluster 匯出的 Helm values。 |
| `gpu-sharing-config.current.yaml` | 來源 cluster 目前使用的 GPU sharing ConfigMap。 |
| `gpu-sharing-icclz1.yaml` | 本機 GPU sharing reference config。 |
| `nvdp-values-before.yaml` | 較早期/完整 values 參考。 |
| `test-gpu-shared.yaml` | GPU sharing smoke test manifest。 |
| `test-gpu-shared-5.yaml` | 多 replica GPU sharing smoke test manifest。 |

目前 live GPU sharing config 使用 time-slicing，`nvidia.com/gpu` replicas 為 `100`。新 cluster 執行 saturation experiments 前請重新確認此值。
