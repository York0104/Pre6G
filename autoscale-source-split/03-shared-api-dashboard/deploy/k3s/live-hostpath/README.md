# Live HostPath Deployment

這條路徑是目前 `icclz2` 上可直接落地並驗證的 `k3s` 版本，不依賴 Harbor push。

適用情境：

- 需要先把服務正式跑起來
- 目前主機的 Docker 尚未安裝 Harbor CA，無法直接 `docker push`
- 可以接受 workload 固定部署在 `icclz2`

## Design

- `autoscale_api`
  - 使用 `python:3.12-slim`
  - Pod 啟動時由 initContainer 安裝 Python dependencies
  - 透過 `hostPath` 掛入 `/home/icclz2/Pre6G`
  - 透過 `hostPath` 掛入 host 上的 `/usr/local/bin/kubectl`
- `cluster-dashboard`
  - 使用 `nginx:1.29-alpine`
  - 直接讀取 repo 內已 build 好的 `cluster-dashboard/dist`
  - 啟動時寫入 `env-config.js`

## Constraints

- 兩個 Deployment 都固定到 `kubernetes.io/hostname=icclz2`
- dashboard 依賴 host 上已有最新 `dist/`
- 若 repo 路徑改變，`hostPath` 也要同步更新
- `autoscale_api` 目前依賴 host 上已有可執行的 `kubectl`

## Deploy

先確認前端已 build：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard
PATH=/home/icclz2/.local/node22/bin:$PATH npm run build
```

再套用：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/deploy/k3s
kubectl apply -f namespace.yaml
kubectl apply -f autoscale-api-rbac.yaml
kubectl create configmap autoscale-api-config \
  -n pre6g-dashboard \
  --from-literal=VM_URL=http://140.113.179.9:31888 \
  --from-literal=NETDATA_URL=http://140.113.179.9:32163 \
  --from-literal=NETDATA_CHILD_URL=http://140.113.179.9:32163 \
  --from-literal=NETDATA_PARENT_BASE_URL=http://140.113.179.9:32163 \
  --from-literal=KSM_URL=http://140.113.179.9:32080 \
  --from-literal=AUTOSCALE_API_CORS_ORIGINS=http://140.113.179.9:30080 \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic autoscale-api-secret \
  -n pre6g-dashboard \
  --from-literal=AUTOSCALE_API_TOKEN=<issued-token> \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap cluster-dashboard-config \
  -n pre6g-dashboard \
  --from-literal=PRE6G_DASHBOARD_API_BASE=http://140.113.179.9:30081 \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic cluster-dashboard-secret \
  -n pre6g-dashboard \
  --from-literal=PRE6G_DASHBOARD_API_TOKEN=<issued-token> \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f live-hostpath/autoscale-api-live.yaml
kubectl apply -f live-hostpath/cluster-dashboard-live.yaml
```

## Verify

```bash
kubectl -n pre6g-dashboard get pods -o wide
kubectl -n pre6g-dashboard logs deploy/autoscale-api
kubectl -n pre6g-dashboard logs deploy/cluster-dashboard
```

Open:

```text
http://140.113.179.9:30080
```

API:

```text
http://140.113.179.9:30081
```

## Update Workflow

### Frontend

若修改 `cluster-dashboard/`：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard
PATH=/home/icclz2/.local/node22/bin:$PATH npm run build
kubectl -n pre6g-dashboard rollout restart deploy/cluster-dashboard
```

### Backend

若修改 `autoscale_api/` 或 `01-monitoring-layer/`：

```bash
kubectl -n pre6g-dashboard rollout restart deploy/autoscale-api
```

## Current Verified Result

截至 `2026-06-06`，這條路徑已實際驗證：

- `http://140.113.179.9:30080` 可開啟 dashboard
- `http://140.113.179.9:30081/` 可回 `Pre6G AutoScale API is running`
- `/api/v1/nodes` 可列出 6 台節點
- `/api/v1/nodes/status` 可回一般 `k3s` nodes 與 `rfsoc4x2-pynq` 的即時 metrics

注意：

- `openwrt_ap` 是否有完整 telemetry，仍取決於其 producer / upstream metrics 是否存在
- `Fan-Cycle Experiment` 頁籤的 API wiring 已於 `2026-06-24` 重建，不應再因舊的路徑對齊錯誤而固定停在 `404`
- 但若目前使用的是 `k3s` live-hostpath API Pod，仍需另外確認該 Pod 內是否具備 experiment control 所需的 `ssh` 與 private runtime 資產；若沒有，請優先改用 host-side `run_local_api.sh` / user-level systemd 驗證 experiment 頁面
