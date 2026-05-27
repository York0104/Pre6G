# 未納入項目說明

本文件說明從 `/home/icclz2/Pre6G` 製作 source split 時刻意排除的內容。

## 大型或可重建項目

```text
cluster-dashboard/node_modules/
cluster-dashboard/dist/
iccl/
iccl_torch_old/
__pycache__/
*.pyc
```

原因：dependency、build output、virtualenv 或 cache，可重新產生，不適合作為交接 source。

## 歷史輸出

```text
experiments/experiments_yolo/results/
experiments/load_injection/tmp/
experiments/model_load/outputs/
experiments/model_load/datasets/
experiments/monitoring/tmp/
```

原因：實驗輸出與暫存資料，不是重建所需 desired state。

## 舊研究線

```text
source/
experiments/load_injection/
experiments/model_load/
experiments/monitoring/
data/
report.md
report.dd
```

原因：不屬於目前 k3s 監控與 thermal YOLO 交接範圍。若需要歷史重現，請回原始 AutoScale repo 查找。

## 備份與 debug

```text
experiments/yolo26_workload/*.bak*
experiments/experiments_yolo/debug/
```

原因：已有 active 版本或屬於 debug/backup，不應混入正式交接。

## 私密 runtime 值

```text
systemd/autoscale-api.env
cluster-dashboard/.env
```

原因：真實環境變數與 secret 應保存在 private handoff，不放入 source split。
