# Thermal YOLO Experiments

本資料夾保存 thermal throttling 與 YOLO latency experiments 所需的 scripts 與 workload 參考。

| 路徑 | 說明 |
| --- | --- |
| `thermal_analysis/` | latency clients、VM aggregator collection、merge、trim、plot scripts。 |
| `yolo26_k8s/` | YOLO API app、Dockerfile、deployment/service manifests。 |
| `experiments_yolo/` | task-oriented single-pod、multi-pod、saturation experiment scripts。 |
| `intent-lab-yolo-workloads.current.yaml` | 來源 cluster 匯出的目前 `intent-lab` deployments/services。 |
| `README_yolo26_3inst.md` | YOLO26 三實例 thermal experiment 參考文件。 |

目前 workload 使用 `local/yolo26n:0.5` 且 `imagePullPolicy: Never`。新 GPU worker 必須先 build/import 此 image，或將 manifests 改成 registry image。

worker-side fan/thermal control 不在此主機；請參考 `../external-worker/README.md`。
