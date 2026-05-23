# Pre6G AutoScale API｜NodePort + systemd 可重建部署紀錄

## 1. 目的

本次整理目標是將原本依賴 `tmux + kubectl port-forward + 手動 uvicorn` 的測試流程，轉換為較穩定、可重建、可開機自動恢復的部署方式。

原本流程：

```text
tmux
├── kubectl port-forward VictoriaMetrics
├── kubectl port-forward Netdata Parent
├── kubectl port-forward DCGM Exporter
└── 手動 uvicorn app.main:app
```

現在流程：

```text
Kubernetes NodePort
├── VictoriaMetrics: http://100.68.32.118:31888
└── Netdata Parent:  http://100.68.32.118:32163

systemd
└── autoscale_api:   http://100.68.32.118:8000
```

此設計讓電腦或服務重啟後，Kubernetes 可自動恢復 NodePort，systemd 可自動啟動 `autoscale_api`。

## 2. 目前完成狀態

| 項目 | 狀態 |
| --- | --- |
| VictoriaMetrics NodePort | 已完成 |
| Netdata Parent NodePort | 已完成 |
| autoscale_api systemd service | 已完成 |
| systemd 開機自動啟動 | 已完成 |
| `/api/v1/nodes` | 已測試成功 |
| `/api/v1/nodes/iccls2/status` | 已測試成功 |
| `/api/v1/nodes/icclz1/status` | 已測試成功 |
| tmux port-forward 依賴 | 可移除 |

## 3. 對外服務入口

| 服務 | URL | 用途 |
| --- | --- | --- |
| VictoriaMetrics | `http://100.68.32.118:31888` | Prometheus-compatible metric query backend |
| VictoriaMetrics Health | `http://100.68.32.118:31888/health` | 健康檢查 |
| Netdata Parent | `http://100.68.32.118:32163` | 即時 node pressure / host metrics |
| AutoScale API | `http://100.68.32.118:8000` | GUI / 前端 / decision logic 使用的 API |
| AutoScale Node List | `http://100.68.32.118:8000/api/v1/nodes` | 節點硬體與基本資訊 |
| AutoScale Node Status | `http://100.68.32.118:8000/api/v1/nodes/{node}/status` | 單一節點即時狀態 |

## 4. GitHub 目錄規劃

```text
AutoScale/
├── k8s-expose/
│   ├── victoria-metrics-nodeport.yaml
│   └── netdata-nodeport.yaml
├── systemd/
│   └── autoscale-api.service
└── docs/
    └── pre6g-autoscale-deployment.md
```

### 4.1 `k8s-expose/`

放 Kubernetes NodePort manifest。

用途：

- 重新建立 VictoriaMetrics / Netdata 對外入口
- 避免每次靠 `kubectl expose` 手動建立
- 固定 NodePort，避免重啟或重建後 port 改變

### 4.2 `systemd/`

放 `autoscale_api` 的 systemd service file。

用途：

- 讓 `autoscale_api` 開機自動啟動
- 永久帶入 `VM_URL / NETDATA_URL` 環境變數
- 避免手動 `source venv`、`export env`、`uvicorn`

### 4.3 `docs/`

放完整部署流程與驗證指令。

用途：

- 讓部署流程可追蹤
- 讓未來換機器或重建環境時可以照文件恢復
- 作為研究紀錄與系統穩定化證明

## 5. Kubernetes NodePort 部署

### 5.1 VictoriaMetrics NodePort

目前服務：

- Namespace: `monitoring`
- Service: `victoria-metrics-nodeport`
- NodePort: `31888`
- Target backend: `vm-victoria-metrics-single-server`
- Port: `8428`

測試：

```bash
curl http://100.68.32.118:31888/health
```

預期結果：

```text
OK
```

### 5.2 Netdata Parent NodePort

目前服務：

- Namespace: `netdata`
- Service: `netdata-nodeport`
- NodePort: `32163`
- Target backend: `netdata`
- Port: `19999`

測試：

```bash
curl -I http://100.68.32.118:32163
```

若有 Netdata Embedded HTTP Server 回應，即代表服務有通。

## 6. systemd：autoscale_api

### 6.1 service file 位置

Repo 中保存位置：

```text
/home/iccls2/AutoScale/systemd/autoscale-api.service
```

systemd 讀取位置：

```text
/etc/systemd/system/autoscale-api.service
```

兩者透過 symlink 連接：

```text
/etc/systemd/system/autoscale-api.service
→ /home/iccls2/AutoScale/systemd/autoscale-api.service
```

建立 symlink：

```bash
sudo ln -sf /home/iccls2/AutoScale/systemd/autoscale-api.service /etc/systemd/system/autoscale-api.service
```

### 6.2 service file 內容

```ini
[Unit]
Description=Pre6G AutoScale API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=iccls2
Group=iccls2

WorkingDirectory=/home/iccls2/AutoScale/autoscale_api

Environment="HOME=/home/iccls2"
Environment="KUBECONFIG=/home/iccls2/.kube/config"
Environment="PYTHONPATH=/home/iccls2/AutoScale:/home/iccls2/AutoScale/autoscale_api"

Environment="VM_URL=http://100.68.32.118:31888"
Environment="NETDATA_PARENT_BASE_URL=http://100.68.32.118:32163"
Environment="NETDATA_URL=http://100.68.32.118:32163"
Environment="NETDATA_CHILD_URL=http://100.68.32.118:32163"

ExecStart=/home/iccls2/AutoScale/iccl/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 6.3 啟用 systemd

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now autoscale-api.service
```

查看狀態：

```bash
sudo systemctl status autoscale-api.service
```

預期狀態：

- `Active: active (running)`
- `Loaded: loaded (...; enabled; ...)`

## 7. API 驗證

### 7.1 Root API

```bash
curl http://100.68.32.118:8000/ | jq
```

預期：

```json
{
  "message": "Pre6G AutoScale API is running"
}
```

### 7.2 Node List

```bash
curl http://100.68.32.118:8000/api/v1/nodes | jq
```

預期：

- `schema = pre6g.node_list.v1`
- `count = 6`

### 7.3 Master Node Status

```bash
curl http://100.68.32.118:8000/api/v1/nodes/iccls2/status | jq
```

預期可看到：

- `node_metrics = vm+netdata`
- `gpu_metrics = dcgm_exporter+k8s`
- CPU usage
- memory usage
- disk root usage

### 7.4 GPU Worker Status

```bash
curl http://100.68.32.118:8000/api/v1/nodes/icclz1/status | jq
```

預期 GPU 狀態：

- `gpu.status = ok`
- `gpu.count = 1`
- `fb_used_mib` 可正常回傳

## 8. 重建流程

若未來重新部署，可依序執行：

```bash
cd ~/AutoScale

kubectl apply -f k8s-expose/victoria-metrics-nodeport.yaml
kubectl apply -f k8s-expose/netdata-nodeport.yaml

sudo ln -sf /home/iccls2/AutoScale/systemd/autoscale-api.service /etc/systemd/system/autoscale-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now autoscale-api.service
```

驗證：

```bash
curl http://100.68.32.118:31888/health
curl -I http://100.68.32.118:32163
curl http://100.68.32.118:8000/ | jq
curl http://100.68.32.118:8000/api/v1/nodes | jq
curl http://100.68.32.118:8000/api/v1/nodes/icclz1/status | jq
```

## 9. 舊流程停用

完成後，不再需要長期使用以下 tmux port-forward：

```bash
kubectl -n monitoring port-forward svc/vm-victoria-metrics-single-server 8428:8428
kubectl -n netdata port-forward svc/netdata 29999:19999
kubectl -n gpu-monitoring port-forward ds/dcgm-exporter 9400:9400
kubectl -n monitoring port-forward deploy/vmagent-victoria-metrics-agent 8429:8429
```

目前正式入口改為：

- VictoriaMetrics: `http://100.68.32.118:31888`
- Netdata Parent: `http://100.68.32.118:32163`
- AutoScale API: `http://100.68.32.118:8000`

## 10. 已知問題

### 10.1 `mirc516-20250605` / `z590-aorus-xtreme`

目前這兩個節點的 `node-exporter / netdata child` 有 Evicted 情況。

原因：

- `DiskPressure`

目前先不處理，因使用者已確認這兩台本來就有硬體或節點狀態問題。

### 10.2 Pydantic schema warning

systemd log 可能出現：

```text
Field name "schema" shadows an attribute in parent "BaseModel"
```

目前不影響 API 功能。

後續若要改善，可將 response model 的欄位：

- `schema`

改為：

- `schema_id`
- `schema_version`

但這會改變 API response 格式，現階段不建議立即處理。

### 10.3 `ICCL-S3-251230` Netdata instant metrics 相容性修復

曾觀察到 `ICCL-S3-251230` 這台節點在 `vm_aggregator` 中出現：

- `target_node_semantic.node_pressure_instant.cpu_usage_percent = null`
- `target_node_semantic.node_pressure_instant.memory_usage_percent = null`
- `target_node_semantic.node_pressure_instant.node_disk_io = null`

但同時：

- Netdata parent 可正常看到該 mirrored host
- `/host/ICCL-S3-251230/api/v1/info` 可正常回應
- chart catalog 中存在 `system.cpu`、`system.ram`、`system.io`

實際根因是：

- `vm_aggregator` 原本使用 Python `urllib` 直接讀 host-scoped Netdata `/api/v1/data`
- 對 `ICCL-S3-251230` 此 host，短視窗查詢偶發回 `HTTP 404`
- 導致 `node_pressure_instant` 被寫成 `null`

目前已在 `vm_aggregator.py` 補上兩層 fallback：

1. 若 host-scoped `/api/v1/data` 在 `urllib` 上回 `404`，改用 `curl` 重抓
2. 若短視窗 `after=-2` 仍無資料，自動退回較長視窗 `after=-60`，再取最新樣本

修復後已驗證 `ICCL-S3-251230` 可正常回傳：

- CPU usage percent
- node CPU used cores
- memory working set bytes
- memory usage percent
- node disk I/O

此修復可避免少數 Netdata child host 因短視窗或 client 相容性差異，而被誤判為 instant metrics 缺失。

## 11. 常用維運指令

查看服務：

```bash
sudo systemctl status autoscale-api.service
```

重啟服務：

```bash
sudo systemctl restart autoscale-api.service
```

查看 log：

```bash
sudo journalctl -u autoscale-api.service -n 100 --no-pager
```

即時追蹤 log：

```bash
sudo journalctl -u autoscale-api.service -f
```

確認 8000 port：

```bash
sudo ss -ltnp | grep ':8000'
```

確認 NodePort：

```bash
kubectl -n monitoring get svc victoria-metrics-nodeport
kubectl -n netdata get svc netdata-nodeport
```

## 12. Git commit 建議

```bash
git add k8s-expose/
git add systemd/
git add docs/pre6g-autoscale-deployment.md

git commit -m "Add reproducible AutoScale API deployment configs"
git push
```

## 13. 本階段結論

本階段已將 AutoScale API 由臨時測試流程升級為穩定服務化部署。

完成前：

```text
tmux + port-forward + manual uvicorn
```

完成後：

```text
Kubernetes NodePort + systemd autoscale_api
```

此部署方式可支援：

- 服務重啟
- 節點重開機
- GitHub 版本追蹤
- 未來重建部署
- GUI / decision API 穩定存取
