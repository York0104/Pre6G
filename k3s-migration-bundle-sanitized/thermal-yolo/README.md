# Thermal YOLO Experiments

本資料夾保存 thermal throttling 與 YOLO latency experiments 所需的 scripts 與 workload 參考。

| 路徑 | 說明 |
| --- | --- |
| `thermal_analysis/` | latency clients、VM aggregator collection、merge、trim、plot scripts。 |
| `yolo26_workload/` | 唯一正式 YOLO API app、Dockerfile、deployment/service manifests 路徑。 |
| `experiments_yolo/` | task-oriented single-pod、multi-pod、saturation experiment scripts。 |
| `intent-lab-yolo-workloads.current.yaml` | 來源 cluster 匯出的目前 `intent-lab` deployments/services。 |
| `README_yolo26_3inst.md` | YOLO26 三實例 thermal experiment 參考文件。 |

目前 repo 仍保留 `local/yolo26n:*` 的實驗路徑；同時已新增 Harbor registry 版本 manifests：

- `yolo26_workload/deployment.registry.yaml`
- `yolo26_workload/yolo26_3inst_icclz1.registry.yaml`

若要在新 GPU worker 直接 pull image，請先看 `../registry/REBUILD_STEPS.md`。

worker-side fan/thermal control 不在此主機；請參考 `../external-worker/README.md`。
