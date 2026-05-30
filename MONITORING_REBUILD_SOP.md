# Monitoring Rebuild SOP

Date: 2026-05-27
Scope: `Pre6G` 監控層與 `Cluster Monitor` dashboard 在新 `k3s` 環境上的正式重建步驟

## How To Use This File

這份文件是重建入口。

建議使用順序：

1. 先照這份 SOP 執行
2. 若某一步需要改值，查 [monitoring-rebuild/REBUILD_PARAMETERS.md](monitoring-rebuild/REBUILD_PARAMETERS.md)
3. 若某一步失敗或遇到異常，查 [MONITORING_REBUILD_K3S_MIGRATION_NOTES.md](MONITORING_REBUILD_K3S_MIGRATION_NOTES.md)
4. 若要看目前測試環境最後做到哪，查 [MONITORING_REBUILD_PROGRESS.md](MONITORING_REBUILD_PROGRESS.md)

## Target Outcome

完成後應具備：

- `VictoriaMetrics`
- `vmagent` cluster collector
- `vmagent-node-local` DaemonSet
- `node-exporter`
- `kube-state-metrics`
- `Netdata parent`
- `Netdata child`
- `Netdata k8s-state`
- `Node Feature Discovery`
- GPU node 自動標記
- `nvidia-device-plugin` 自動排到 GPU node
- `dcgm-exporter` 自動排到 GPU node
- `vm_aggregator` 可查詢
- `autoscale_api` 可啟動
- dashboard 的 `Cluster Monitor` 可使用

## Step 0: Prepare Parameters

先確認以下值：

- `CONTROL_PLANE_IP`
- `VM_NODEPORT`
- `NETDATA_NODEPORT`
- `MONITORING_NS`
- `QUERY_NS`

參考：

- [monitoring-rebuild/REBUILD_PARAMETERS.md](monitoring-rebuild/REBUILD_PARAMETERS.md)

至少要重新檢查：

- [monitoring-rebuild/10-victoria-metrics.yaml](monitoring-rebuild/10-victoria-metrics.yaml)
- [monitoring-rebuild/20-vmagent.yaml](monitoring-rebuild/20-vmagent.yaml)
- [monitoring-rebuild/45-nvidia-device-plugin.yaml](monitoring-rebuild/45-nvidia-device-plugin.yaml)
- [monitoring-rebuild/55-netdata.yaml](monitoring-rebuild/55-netdata.yaml)
- [monitoring-rebuild/60-netdata-child-stream-config.yaml](monitoring-rebuild/60-netdata-child-stream-config.yaml)
- [monitoring-rebuild/71-nfd-gpu-alias-rule.yaml](monitoring-rebuild/71-nfd-gpu-alias-rule.yaml)

## Step 1: Confirm K3s Base Health

```bash
kubectl get nodes -o wide
kubectl get pods -A
```

成功條件：

- 所有預期 node 都 `Ready`
- 沒有明顯 cluster-level crash loop

## Step 2: Deploy Namespaces

```bash
kubectl apply -f monitoring-rebuild/00-namespaces.yaml
```

驗證：

```bash
kubectl get ns | grep -E 'monitoring|gpu-monitoring|netdata|node-feature-discovery'
```

## Step 3: Deploy Core Monitoring

```bash
kubectl apply -f monitoring-rebuild/10-victoria-metrics.yaml
kubectl apply -f monitoring-rebuild/20-vmagent.yaml
kubectl apply -f monitoring-rebuild/30-node-exporter.yaml
kubectl apply -f monitoring-rebuild/40-kube-state-metrics.yaml
```

驗證：

```bash
kubectl -n monitoring get pods -o wide
```

成功條件：

- `vm-victoria-metrics-single-server-*` `Running`
- `vmagent-victoria-metrics-agent-*` `Running`
- `vmagent-node-local-*` 每台 node 都有
- `node-exporter-*` 每台 node 都有
- `kube-state-metrics-*` `Running`

## Step 4: Deploy Netdata

先套完整 stack：

```bash
kubectl apply -f monitoring-rebuild/55-netdata.yaml
```

再套目前驗證可用的 child stream override：

```bash
kubectl apply -f monitoring-rebuild/60-netdata-child-stream-config.yaml
kubectl -n netdata rollout restart daemonset/netdata-child
```

驗證：

```bash
kubectl -n netdata get pods -o wide
kubectl -n netdata get svc
```

成功條件：

- `netdata-parent-*` `Running`
- `netdata-child-*` 每台 node 都有
- `netdata-k8s-state-*` `Running`
- `netdata-nodeport` 存在且 NodePort 為預期值

若 `netdata-child` 在 `hostNetwork` 下遇到 DNS 問題：

- 查 [MONITORING_REBUILD_K3S_MIGRATION_NOTES.md](MONITORING_REBUILD_K3S_MIGRATION_NOTES.md)
- 重點看 `Netdata child stream 改走 NodePort` 的修法

## Step 5: Deploy GPU Auto-Discovery

```bash
kubectl apply -f monitoring-rebuild/70-node-feature-discovery.yaml
kubectl apply -f monitoring-rebuild/71-nfd-gpu-alias-rule.yaml
```

驗證：

```bash
kubectl -n node-feature-discovery get pods -o wide
kubectl get node --show-labels | grep 'feature.node.kubernetes.io/pci-10de.present'
```

成功條件：

- `nfd-master` / `nfd-worker` 正常
- 有 NVIDIA GPU 的 node 自動出現 `feature.node.kubernetes.io/pci-10de.present=true`

## Step 6: Deploy NVIDIA Device Plugin

```bash
kubectl apply -f monitoring-rebuild/45-nvidia-device-plugin.yaml
```

驗證：

```bash
kubectl -n kube-system get ds nvidia-device-plugin-daemonset -o wide
kubectl -n kube-system get pods -l name=nvidia-device-plugin-ds -o wide
```

成功條件：

- `nvidia-device-plugin-daemonset` 存在
- pod 只排到有 `feature.node.kubernetes.io/pci-10de.present=true` 的 GPU node

## Step 7: Confirm GPU Node Host Readiness

```bash
kubectl get node <gpu-node> -o jsonpath='{.status.capacity.nvidia\.com/gpu}{"\n"}'
kubectl get node <gpu-node> -o jsonpath='{.status.allocatable.nvidia\.com/gpu}{"\n"}'
```

成功條件：

- 至少有 `1`

若仍為空值：

```bash
kubectl -n kube-system get pods -l name=nvidia-device-plugin-ds -o wide
kubectl -n gpu-monitoring get pods -l app.kubernetes.io/name=dcgm-exporter -o wide
```

若看到 `failed to initialize NVML` 或 `Driver/library version mismatch`，先修主機 NVIDIA stack。

## Step 8: Deploy GPU Monitoring

```bash
kubectl apply -f monitoring-rebuild/50-dcgm-exporter.yaml
```

驗證：

```bash
kubectl -n gpu-monitoring get pods -o wide
```

成功條件：

- `dcgm-exporter-*` 只排到 GPU node
- pod 為 `Running`

## Step 9: Validate Metrics Ingestion

```bash
kubectl get pods -A
curl "http://<CONTROL_PLANE_IP>:<VM_NODEPORT>/api/v1/query?query=up"
curl "http://<CONTROL_PLANE_IP>:<VM_NODEPORT>/api/v1/query?query=node_uname_info"
```

若 GPU node 正常，也可查：

```bash
curl "http://<CONTROL_PLANE_IP>:<VM_NODEPORT>/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP"
```

## Step 10: Validate VM Aggregator

```bash
bash autoscale-source-split/01-monitoring-layer/run_vm_aggregator_once.sh iccl-cluster-z2
bash autoscale-source-split/01-monitoring-layer/run_vm_aggregator_once.sh icclz3
```

成功條件：

- `collector_status = ok`

## Step 11: Start API And Dashboard

正式重建優先使用 `systemd` 啟動 API：

```bash
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env
sudo cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autoscale-api.service
```

接著務必編輯 `autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env`：

- 把所有 `<CONTROL_PLANE_IP>` / `<control-plane-ip>` placeholder 換成真實 host-side 端點
- 填入有效的 `AUTOSCALE_API_TOKEN`
- 若保留 placeholder 值，`autoscale_api` 會 fail-fast 拒絕啟動

目前已驗證可用的 host-side 端點為：

- `VM_URL=http://140.113.179.9:31888`
- `NETDATA_PARENT_BASE_URL=http://140.113.179.9:32163`
- `NETDATA_URL=http://140.113.179.9:32163`
- `NETDATA_CHILD_URL=http://140.113.179.9:32163`
- `KSM_URL=http://140.113.179.9:32080`

再啟 dashboard：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard
bash run_local_dashboard.sh
```

驗證：

```bash
export AUTOSCALE_API_BASE=http://127.0.0.1:8000
export AUTOSCALE_API_TOKEN=$(grep '^AUTOSCALE_API_TOKEN=' /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/autoscale-api.env | cut -d= -f2-)
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" "$AUTOSCALE_API_BASE/"
curl -H "Authorization: Bearer $AUTOSCALE_API_TOKEN" "$AUTOSCALE_API_BASE/api/v1/nodes/status" | jq
curl -I http://127.0.0.1:5174/
```

瀏覽器：

- `http://<CONTROL_PLANE_IP>:5174/`

## Step 12: Final Acceptance Checklist

1. `kubectl get pods -A`
2. `kubectl get nodes -o wide`
3. `vmagent-node-local` 每台 node 都在
4. `node-exporter` 每台 node 都在
5. `Netdata child` 每台 node 都在
6. `NFD` 正常
7. GPU node 自動出現 `feature.node.kubernetes.io/pci-10de.present=true`
8. GPU node 正常時，`nvidia.com/gpu` 有值
9. `dcgm-exporter` 只在 GPU node 上
10. `run_vm_aggregator_once.sh <node>` 回 `collector_status = ok`
11. `autoscale_api` 可回應
12. dashboard `Cluster Monitor` 可正常顯示資料

## Fast Failure Routing

### A. 一般 worker 沒資料

先查：

- `node-exporter`
- `vmagent-node-local`
- `netdata-child`

### B. GPU node 沒有 `nvidia.com/gpu`

先查：

1. 是否已有 `feature.node.kubernetes.io/pci-10de.present=true`
2. `nvidia-device-plugin` 是否有排上
3. host `nvidia-smi` 是否正常

### C. Netdata host-scoped 404

先查：

- `netdata-child` 是否真的 stream 到 parent
- `60-netdata-child-stream-config.yaml` 是否已在 `55-netdata.yaml` 之後重新套用

### D. API / dashboard 抓不到資料

先查：

1. `autoscale_api` 是否正常啟動
2. dashboard `.env` 的 API base 是否正確
3. CORS 是否允許 dashboard 來源
