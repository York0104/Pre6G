# Gemma 4 vLLM Serving

這個目錄保存 `Gemma 4` 在目前 `k3s` 叢集上的第一版 `vLLM` serving manifests。

## Files

- `namespace.yaml`
- `pvc.yaml`
- `deployment.yaml`
- `service.yaml`
- `benchmark-job.yaml`

## Current Assumptions

- target node: `iccl-s3-251230`
- GPU: single `RTX 4090 24GB`
- runtime class: `nvidia`
- storage class: `local-path`
- exposed port: `8000`
- metrics port name: `http-metrics`

## Important Notes

- `deployment.yaml` 已改成 `strategy: Recreate`，避免單 GPU node 更新時卡在第二個 Pending replica。
- `startupProbe` 已納入，避免 Gemma 4 冷啟動期間被過早 liveness kill。
- `service.yaml` 的 port name 保持 `http-metrics`，供 vmagent 的 pod discovery scrape job 自動匹配。

## Validation

第一版實測已確認：

- Pod 可成功下載並載入 `unsloth/gemma-4-E2B-it-qat-w4a16`
- `/health` 與 `/metrics` 可回 `200`
- `vllm:*` 指標可被 vmagent 抓取並進入 VictoriaMetrics

若要做非零流量驗證，可再套用 `benchmark-job.yaml`。

目前 `benchmark-job.yaml` 預設排到 `icclz2`，因為本輪重建中這個節點比 `icclz1` 更適合作為 benchmark client。
