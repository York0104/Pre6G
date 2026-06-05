# k3s Deployment Guide

本資料夾提供 `03-shared-api-dashboard` 在 `k3s` 上的最小可用部署樣板，包含：

- `autoscale_api` backend
- `cluster-dashboard` frontend
- API 的 node-read RBAC
- ConfigMap / Secret 範本
- 可選的 Ingress 樣板

## Files

| Path | Purpose |
| --- | --- |
| `namespace.yaml` | 建立 `pre6g-dashboard` namespace。 |
| `autoscale-api-rbac.yaml` | 允許 API Pod 讀取 Kubernetes nodes。 |
| `autoscale-api-configmap.example.yaml` | API 非敏感 env 範本。 |
| `autoscale-api-secret.example.yaml` | API token secret 範本。 |
| `autoscale-api-deployment.yaml` | API Deployment + NodePort Service。 |
| `cluster-dashboard-configmap.example.yaml` | dashboard runtime config 範本。 |
| `cluster-dashboard-secret.example.yaml` | dashboard runtime token secret 範本。 |
| `cluster-dashboard-deployment.yaml` | dashboard Deployment + NodePort Service。 |
| `ingress.example.yaml` | 若 cluster 內有 ingress-nginx，可改用 host-based access。 |
| `live-hostpath/` | 目前 `icclz2` 已實際驗證可用的 hostPath 版部署。 |

## 1. Build Images

以下指令以 repo root 為 build context，因為 `autoscale_api` image 需要一併打包：

- `autoscale-source-split/01-monitoring-layer`
- `autoscale-source-split/03-shared-api-dashboard`

### autoscale_api

```bash
cd /home/icclz2/Pre6G
docker build \
  -f autoscale-source-split/03-shared-api-dashboard/autoscale_api/Dockerfile \
  -t harbor.iccl.local:8088/pre6g/autoscale-api:0.1 \
  .
```

### cluster-dashboard

```bash
cd /home/icclz2/Pre6G
docker build \
  -f autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/Dockerfile \
  -t harbor.iccl.local:8088/pre6g/cluster-dashboard:0.1 \
  .
```

若目標 cluster 需要 Harbor push / pull，請先依照：

- [k3s-migration-bundle-sanitized/registry/REBUILD_STEPS.md](../../../k3s-migration-bundle-sanitized/registry/REBUILD_STEPS.md)

完成 registry 與 `k3s` node pull path。

## 2. Push Images

```bash
docker push harbor.iccl.local:8088/pre6g/autoscale-api:0.1
docker push harbor.iccl.local:8088/pre6g/cluster-dashboard:0.1
```

## 3. Prepare Config

先複製 example 檔案，再填入真實值：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/deploy/k3s
cp autoscale-api-configmap.example.yaml autoscale-api-configmap.yaml
cp autoscale-api-secret.example.yaml autoscale-api-secret.yaml
cp cluster-dashboard-configmap.example.yaml cluster-dashboard-configmap.yaml
cp cluster-dashboard-secret.example.yaml cluster-dashboard-secret.yaml
```

至少需要更新：

- `autoscale-api-configmap.yaml`
  - `VM_URL`
  - `NETDATA_URL`
  - `NETDATA_CHILD_URL`
  - `NETDATA_PARENT_BASE_URL`
  - `KSM_URL`
  - `AUTOSCALE_API_CORS_ORIGINS`
- `autoscale-api-secret.yaml`
  - `AUTOSCALE_API_TOKEN`
- `cluster-dashboard-configmap.yaml`
  - `PRE6G_DASHBOARD_API_BASE`
- `cluster-dashboard-secret.yaml`
  - `PRE6G_DASHBOARD_API_TOKEN`

建議 `PRE6G_DASHBOARD_API_BASE` 直接填 dashboard 使用者可直接連到的 API 外部入口，例如：

```text
http://140.113.179.9:30081
```

注意：frontend 程式碼是在瀏覽器執行，不是在 Pod 內執行，因此不能把 `*.svc.cluster.local` 直接塞給瀏覽器。

## 4. Apply Manifests

```bash
kubectl apply -f namespace.yaml
kubectl apply -f autoscale-api-rbac.yaml
kubectl apply -f autoscale-api-configmap.yaml
kubectl apply -f autoscale-api-secret.yaml
kubectl apply -f autoscale-api-deployment.yaml
kubectl apply -f cluster-dashboard-configmap.yaml
kubectl apply -f cluster-dashboard-secret.yaml
kubectl apply -f cluster-dashboard-deployment.yaml
```

若要使用 Ingress：

```bash
kubectl apply -f ingress.example.yaml
```

## 5. Verify

### Pod / Service

```bash
kubectl -n pre6g-dashboard get pods
kubectl -n pre6g-dashboard get svc
```

### API health

```bash
kubectl -n pre6g-dashboard logs deploy/autoscale-api
kubectl -n pre6g-dashboard port-forward svc/autoscale-api 8000:8000
```

另一個 shell：

```bash
curl -H "Authorization: Bearer <AUTOSCALE_API_TOKEN>" http://127.0.0.1:8000/
curl -H "Authorization: Bearer <AUTOSCALE_API_TOKEN>" http://127.0.0.1:8000/api/v1/nodes
```

### Dashboard access

若沿用 `NodePort`：

```text
http://<k3s-control-plane-ip>:30080
```

### API access

API 也會以 `NodePort` 暴露，供 dashboard 瀏覽器端呼叫：

```text
http://<k3s-control-plane-ip>:30081
```

## Notes

- `autoscale_api` 已改為優先嘗試 `in-cluster config`，因此在 Pod 內不需要額外掛 `~/.kube/config`。
- 這版 frontend 不再把 API base / token 硬編進 build 產物；改 `ConfigMap/Secret` 後重建 Pod 即可生效。
- 兩個 Deployment 都預設使用 `harbor-pull-secret`；若目標 namespace 尚未有這個 secret，請先建立或從既有 namespace 複製。
- `Fan-Cycle Experiment` 與 `YOLO demo` API 仍非本輪正式驗證範圍。若它們要在 `k3s` 內完整可用，還需要再補齊相關依賴服務與權限。

## Current Validated Path On icclz2

截至 `2026-06-06`，目前這台主機上已實際驗證可用的是：

- [live-hostpath/README.md](./live-hostpath/README.md)

原因是當前 Docker host 尚未完成 Harbor CA trust，因此 `docker push harbor.iccl.local:8088/...` 仍會卡在自簽 CA 驗證。
為了先完成正式可用部署，已改採：

- API 與 dashboard 都固定在 `icclz2`
- API 使用 `python:3.12-slim` + hostPath repo source
- dashboard 使用 `nginx:1.29-alpine` + hostPath `dist/`

這條路徑已實際驗證：

- `autoscale-api` NodePort `30081` 可回 `200`
- `/api/v1/nodes` 可回 6 台節點，含 `rfsoc4x2-pynq` 與 `openwrt_ap`
- `cluster-dashboard` NodePort `30080` 可回首頁
