# Normal-only Smoke Operator Checklist

Milestone 1 只驗證資料鏈，不做 calibration sweep，不做 cooling-constrained，不做任何 fan / CoolerControl / Kubernetes control。

## 必填設定

從 template 複製出 operator-reviewed config：

```bash
cp autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/configs/normal_only_smoke.operator.template.json \
   /tmp/normal_only_smoke.operator.json
```

人工填入：

- `endpoint.url`
- `node_gpu_identity.node_name`
- `node_gpu_identity.gpu_uuid`
- `node_gpu_identity.gpu_model`
- `container_image`
- `yolo_model`
- `normal_live_smoke.payload_mix`
- `workload_profiles.smoke_low.payload_mix`
- `telemetry_runtime.node`
- `telemetry_runtime.nvidia_smi_ssh_alias`
- `safety.operator_max_gpu_temp_c`

本 repo 也提供一份依既有 YOLO 實驗路徑預填部分欄位的 draft：

```text
autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/configs/normal_only_smoke.icclz2.draft.json
```

這份 draft 已填入既有 sanity image 與 VM/Netdata URL，但 endpoint、node/GPU identity 與 safety limit 仍必須由 operator 確認後才可 live 使用。

## 啟動前確認

- `operator_max_gpu_temp_c` 依現場設備政策設定，不由程式猜測。
- endpoint、image payload、node、GPU identity 正確。
- 沒有其他非預期 GPU workload。
- telemetry 可取得 GPU temperature、SM clock、power、utilization。
- config 不含 fan mode、CoolerControl、cooling intervention、Kubernetes scale/restart/delete。

## Preflight

```bash
python autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config /tmp/normal_only_smoke.operator.json \
  --preflight-only \
  --normal-only
```

## Live Smoke

只有 preflight 通過後才可由 operator 手動執行：

```bash
CONFIRM_NORMAL_SMOKE=YES python autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py \
  --config /tmp/normal_only_smoke.operator.json \
  --normal-only \
  --run-normal-smoke
```

## 成功判定

- scheduled arrivals 與 target offered RPS 一致。
- `dropped_max_inflight` 接近 0。
- completion-binned throughput 與 completion timestamp 合理。
- 無持續 timeout / error burst。
- GPU temperature 未接近 operator 上限。
- SM clock 無無法解釋的異常降頻。
- GPU、VM、request log timestamp 可對齊。
- raw request log、arrival summary、completion summary、manifest、safety record 齊全。

若出現 timeout、drop 或 telemetry gap，不要提高 RPS；先修資料鏈或 client saturation。
