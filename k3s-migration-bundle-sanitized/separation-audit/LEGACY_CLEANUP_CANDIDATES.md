# Legacy / Cleanup Candidates

本文件是 audit 清單，不代表已刪除原始 AutoScale repo 內容。交接包只納入目前重建需要的 source/config；不確定是否仍需歷史重現的項目保留在原 repo。

## 已排除的明確備份/重複檔

| 檔案 | 判斷 |
| --- | --- |
| `experiments/yolo26_k8s/Dockerfile.bak_before_yolo26m_repeat_20260428_100248` | Dockerfile 備份，已有 active Dockerfile。 |
| `experiments/yolo26_k8s/app.py.bak_before_yolo26m_repeat_20260428_100248` | YOLO app 備份，已有 active app。 |
| `experiments/experiments_yolo/debug/gpu-sharing-config.backup.yaml` | debug/backup GPU sharing config。 |
| `rebuild_bundle_temp/` | 臨時 export；有用的 Helm/k8s reference 已整理進 migration bundle。 |

## Demo / Smoke / Test

| 檔案 | 判斷 |
| --- | --- |
| `hello-deploy.yaml` | 簡單測試 deployment，不屬於目前重建主線。 |
| `test.py` / `source/test.py` / `utils/test.py` | 測試檔，非目前 workflow 必要項。 |
| `monitor_cli_demo.py` | aggregator demo wrapper，非必要。 |
| `observe_loop.sh` | 較早期 observation helper，非必要。 |
| `test-worker-icclz1.yaml` / `test-worker-z590.yaml` | nginx node placement smoke test。 |
| `vm-aggregator-stuck-pod.yaml` | runtime pod 狀態 dump，不是 reusable desired state。 |

## Aggregator 判斷

目前 source split 僅保留主要 aggregator 名稱：

```text
01-monitoring-layer/vm_aggregator.py
```

它承接先前新版 aggregator 的角色；交付包內已統一使用 `vm_aggregator.py`。

## 歷史 workload / research areas

| 路徑 | 判斷 |
| --- | --- |
| `source/` | 舊 workload collectors/demos，例如 MySQL、Nginx、YOLOv5、PIDNet、Real-ESRGAN、ZoneMinder。 |
| `experiments/load_injection/` | CPU/memory load injection 研究線，非目前 thermal YOLO 必要依賴。 |
| `experiments/model_load/` | LightGBM/ResNet resource profile 研究線。 |
| `experiments/monitoring/` | 舊 monitoring plot/helper，不是目前重建所需。 |
| `data/` | 歷史資料與舊 workload script。 |
| `report.md` / `report.dd` | 舊報告/輸出。 |

## 大型或產生式資料

```text
cluster-dashboard/node_modules/
cluster-dashboard/dist/
iccl/
iccl_torch_old/
experiments/experiments_yolo/results/
experiments/model_load/outputs/
experiments/model_load/datasets/
experiments/load_injection/tmp/
__pycache__/
*.pyc
tools/cloudflared
```

原因：可重建依賴、virtualenv、historical outputs、cache 或本機 binary，不應放入正式交接。
