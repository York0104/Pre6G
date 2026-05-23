# 02 Experiment Layer

本層保存目前 thermal YOLO 實驗 workflow。它依賴監控層提供 metrics/API，但監控層不依賴本層。

## 主要用途

- 部署 YOLO26 k8s workload。
- 產生 inference traffic 並記錄 latency。
- 透過 worker 端 `gpu-tempctl-lab` 控制 fan/thermal cycle。
- 收集 `vm_aggregator.py` metrics，合併 latency、thermal phase 與 GPU/Node 指標。
- 產生實驗 summary、dataset 與圖表。

## 根目錄檔案與目錄

| 路徑 | 說明 |
| --- | --- |
| `DEPENDENCY_TRACE.md` | 說明本層未依賴舊的 `experiments/load_injection/`、`model_load/`、`monitoring/`，並追蹤 fan/load 來源。 |
| `experiments_yolo/` | 目前主要 YOLO 實驗 workflow，包含 saturation、single pod、fault fan、bgload fan cycle。 |
| `scripts/` | 較早期或通用的 YOLO26 thermal/rate sweep 腳本。 |
| `thermal_analysis/` | thermal YOLO 資料收集、合併、繪圖與 batch runner。 |
| `yolo26_k8s/` | YOLO26 inference service Dockerfile、app 與 k8s manifests。 |

## `experiments_yolo/common/`

| 檔案 | 說明 |
| --- | --- |
| `request_client_serial.py` | 單 worker/固定 interval 的 inference latency client。 |
| `request_client_parallel.py` | 多 worker/concurrency inference client，用於壓力或 saturation 測試。 |
| `run_thermal_cycle_from_master.sh` | 從 master 透過 SSH 啟動 worker fan/thermal cycle。 |
| `run_bgload_fan_cycle_from_master.sh` | 啟動 worker GPU background workload 與 fan cycle。 |
| `save_vm_aggregator_snapshot.py` | 執行 aggregator 並保存單次 snapshot。 |
| `extract_vmagg_training_features.py` | 從 aggregator timeseries 萃取 training-ready features。 |
| `task3_find_stable_window.py` | 找出 task3 saturation 實驗中的穩定量測窗口。 |
| `analyze_single_pod_bgload_fan_cycle.py` | 分析單 pod + background GPU load + fan cycle 結果。 |
| `analyze_single_pod_serial.py` | 分析單 pod serial latency 結果。 |
| `analyze_single_pod_serial_fault_fan.py` | 分析固定低風扇/fault fan 情境下的 serial latency 與 thermal phase。 |
| `analyze_task3_stable_latency.py` | 分析 task3 saturation 穩定窗口內 latency。 |
| `plot_resource_overview.py` | 繪製 CPU/GPU/resource overview。 |
| `plot_single_pod_bgload_fan_cycle.py` | 繪製 bgload fan cycle 實驗圖。 |
| `plot_single_pod_serial_fault_fan.py` | 繪製 fault fan 實驗圖。 |
| `plot_task3_full_timeline.py` | 繪製 task3 完整 timeline。 |

## `experiments_yolo/` 實驗子目錄

| 路徑 | 說明 |
| --- | --- |
| `saturation_multi_pod/` | 多 pod saturation 實驗；含 workload manifest 與 service-load runner。 |
| `single_pod_serial/` | 單 pod serial inference 量測。 |
| `single_pod_serial_fault_fan/` | 單 pod serial 搭配固定低風扇/故障情境。 |
| `single_pod_bgload_fan_cycle/` | 單 pod measurement 搭配 worker background GPU load 與 fan cycle。 |
| `yolo_demo/` | YOLO demo 參考文件；非核心重建項目。 |
| `run4task.sh` | 舊 task runner 參考。 |

## `experiments_yolo/saturation_multi_pod/`

| 檔案 | 說明 |
| --- | --- |
| `README_task3_gpu_saturation.md` | task3 GPU saturation 實驗說明。 |
| `find_focus_pod.sh` | 找出 focus pod 的 helper。 |
| `run_task3_service_load_with_metrics.sh` | 執行 task3 service load，並同步收集 VM aggregator metrics。 |
| `yolo26_task3_saturation.yaml` | focus/background YOLO pods 與 Service manifest。 |

## `experiments_yolo/single_pod_bgload_fan_cycle/`

| 檔案 | 說明 |
| --- | --- |
| `README_single_pod_bgload_fan_cycle.md` | 單 pod + background load + fan cycle 實驗說明。 |
| `run_single_pod_bgload_fan_cycle.sh` | 執行單次 bgload fan cycle 實驗。 |
| `run_single_pod_bgload_fan_cycle_loop.sh` | 連續執行多次 bgload fan cycle 實驗。 |

## `experiments_yolo/single_pod_serial/`

| 檔案 | 說明 |
| --- | --- |
| `README_single_pod_serial.md` | 單 pod serial 實驗說明。 |
| `run_single_pod_serial_with_metrics.sh` | 執行 serial request 並收集 metrics。 |

## `experiments_yolo/single_pod_serial_fault_fan/`

| 檔案 | 說明 |
| --- | --- |
| `README_single_pod_serial_fault_fan.md` | 單 pod serial + fault fan 實驗說明。 |
| `run_single_pod_serial_fault_fan.sh` | 執行固定低風扇/fault fan 情境實驗。 |

## `experiments_yolo/yolo_demo/`

| 檔案 | 說明 |
| --- | --- |
| `README.md` | YOLO demo 操作與設計說明。 |

## `scripts/`

| 檔案 | 說明 |
| --- | --- |
| `README_yolo26_3inst.md` | YOLO26 三實例 thermal 實驗說明。 |
| `run_A_normal_baseline_yolo.sh` | baseline YOLO 實驗 runner。 |
| `run_B_thermal_yolo26_3inst.sh` | thermal YOLO smoke/long run runner。 |
| `run_C_thermal_yolo26_3inst_cycles.sh` | 多 cycle thermal YOLO runner。 |
| `run_yolo26_singlepod_rate_sweep.sh` | 單 pod closed-loop rate sweep。 |
| `run_yolo26_singlepod_async_rate_sweep.sh` | 單 pod async/open-loop rate sweep。 |
| `train_normal_behavior_xgb.py` | 使用實驗資料訓練 normal behavior XGBoost model 的參考程式。 |

## `thermal_analysis/`

| 檔案 | 說明 |
| --- | --- |
| `collect_vm_aggregator_csv.py` | 週期性執行 `vm_aggregator.py` 並輸出 timeseries CSV。 |
| `build_thermal_yolo_dataset.py` | 建立 thermal YOLO labeled dataset。 |
| `detect_service_outage.py` | 偵測 inference service outage。 |
| `live_cycle_plot.py` | 針對進行中的 thermal cycle 產生即時圖。 |
| `merge_latency.py` | 合併 latency CSV。 |
| `merge_run.py` | 合併單次 run 的 thermal 與 latency 輸出。 |
| `merge_thermal_yolo_cycles.py` | 合併多個 thermal YOLO cycle dataset。 |
| `merge_vmagg_into_thermal_dataset.py` | 將 VM aggregator metrics 合併進 thermal dataset。 |
| `plot_latency_results.py` | 繪製 latency 統計與結果圖。 |
| `plot_thermal_smclock_latency.py` | 同圖檢視 temperature、fan、SM clock、latency。 |
| `plot_thermal_yolo_dataset.py` | 繪製 thermal YOLO dataset 概覽。 |
| `run_cycle_from_master.sh` | 舊版 master 端 cycle runner。 |
| `run_yolo26_k8s_batch.sh` | 批次執行 YOLO26 k8s experiment。 |
| `run_yolo26_k8s_experiment.sh` | 單次 YOLO26 k8s experiment runner。 |
| `run_yolo26_k8s_multi_cycle.sh` | 多 cycle YOLO26 k8s runner。 |
| `summarize_multi_cycle.py` | 產生 multi-cycle summary。 |
| `summarize_service_latency.py` | 產生 service latency summary。 |
| `trim_latency_to_aligned.py` | 將 latency CSV 修剪到對齊時間窗。 |
| `yolo26_async_openloop_client.py` | async/open-loop YOLO26 request client。 |
| `yolo26_latency_client.py` | YOLO26 latency client。 |
| `yolo26_latency_client_stable.py` | 較穩定版本的 YOLO26 latency client。 |

## `yolo26_k8s/`

| 檔案 | 說明 |
| --- | --- |
| `Dockerfile` | 建立 YOLO26 inference image。 |
| `app.py` | FastAPI/HTTP inference service。 |
| `requirements.txt` | YOLO26 service Python dependencies。 |
| `deployment.yaml` | 基本 YOLO26 Deployment。 |
| `service.yaml` | YOLO26 Service。 |
| `yolo26_3inst_icclz1.yaml` | 三實例 GPU shared workload manifest。 |
| `test_images/sanity_input.png` | inference sanity test 圖片。 |

## 重要依賴

worker fan control 與 GPU background workload 不在本機；需由 worker 的 `/home/icclz1/gpu-tempctl-lab` 提供。詳見 `DEPENDENCY_TRACE.md`。
