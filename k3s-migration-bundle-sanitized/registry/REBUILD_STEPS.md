# Harbor Rebuild Steps

本文件描述如何在新的 k3s cluster 上重建 YOLO26 registry workflow。建議先完成 Harbor pull path，再決定是否啟用 Kaniko build。

## 0. 前置條件

- Harbor 已可從所有 k3s node 連線。
- 每個 GPU node 已具備 NVIDIA driver 與可用的 container runtime。
- `intent-lab` namespace 已存在。
- 目前正式支援的 YOLO image tag 為 `0.1`。
- `intent-lab` 的歷史匯出快照仍可見 `0.5`，但這不再是目前建議的 rebuild 標準。

## 1. 建立 Harbor project 與帳號

建議至少建立：

- project: `pre6g`
- repo: `pre6g/yolo26n`
- robot account: pull / push 分離，或至少一組可先完成 PoC

正式實驗請額外記錄 digest：

```text
harbor.iccl.local/pre6g/yolo26n@sha256:<digest>
```

## 2. 設定每個 k3s node 的 private registry

複製樣板：

```bash
sudo mkdir -p /etc/rancher/k3s
sudo cp k3s-migration-bundle-sanitized/registry/harbor-registries.yaml.example /etc/rancher/k3s/registries.yaml
```

若使用自簽 CA，再放置：

```bash
sudo cp harbor-ca.crt /etc/rancher/k3s/harbor-ca.crt
```

套用後重啟：

```bash
sudo systemctl restart k3s
sudo systemctl restart k3s-agent
```

若某些 node 不是 server 或不是 agent，只需重啟對應服務。

## 3. 建立 namespace 與 secrets

套用 namespace：

```bash
kubectl apply -f k3s-migration-bundle-sanitized/registry/image-build.namespace.yaml
```

建立 secret 有兩種方式。

方式 A：直接用指令建立：

```bash
kubectl -n image-build create secret docker-registry harbor-push-secret \
  --docker-server=harbor.iccl.local \
  --docker-username='<HARBOR_ROBOT_ACCOUNT>' \
  --docker-password='<HARBOR_ROBOT_TOKEN>' \
  --docker-email='noreply@pre6g.local'

kubectl -n intent-lab create secret docker-registry harbor-pull-secret \
  --docker-server=harbor.iccl.local \
  --docker-username='<HARBOR_ROBOT_ACCOUNT>' \
  --docker-password='<HARBOR_ROBOT_TOKEN>' \
  --docker-email='noreply@pre6g.local'
```

方式 B：先編輯 `imagepullsecret.example.yaml` 再 `kubectl apply -f`。

## 4. 先驗證 worker 可以 pull Harbor image

建議先跳過 Kaniko，直接用一個已存在的 image 測通 pull path：

```bash
sudo crictl pull harbor.iccl.local/pre6g/yolo26n:0.1
```

或：

```bash
sudo k3s ctr images pull harbor.iccl.local/pre6g/yolo26n:0.1
```

如果這一步失敗，先不要進到 workload deploy。請改看 `VERIFY_REGISTRY_PULL.md`。

## 5. 建立 image

### 選項 A：手動 build + push

先在可連 Harbor 的 build host 上使用目前 source-level build context：

```bash
cd autoscale-source-split/02-experiment-layer/yolo26_workload
docker build -t harbor.iccl.local/pre6g/yolo26n:0.1 .
docker push harbor.iccl.local/pre6g/yolo26n:0.1
```

如果環境不用 Docker，也可改用 Podman、BuildKit 或其他 builder，只要最後 push 到同一個 Harbor repo 即可。

### 選項 B：Kaniko build job

編輯 `kaniko-yolo26-build-job.yaml` 內的 repo ref、image tag、cache repo 與必要 secret 名稱後：

```bash
kubectl apply -f k3s-migration-bundle-sanitized/registry/kaniko-yolo26-build-job.yaml
kubectl -n image-build logs -f job/kaniko-build-yolo26n
```

建議把 Git ref 固定到 commit SHA，不要只用 branch name。

## 6. 部署 registry 版 YOLO

單實例：

```bash
kubectl apply -f k3s-migration-bundle-sanitized/thermal-yolo/yolo26_workload/deployment.registry.yaml
kubectl -n intent-lab rollout status deploy/yolo26n-detect
```

三實例：

```bash
kubectl apply -f k3s-migration-bundle-sanitized/thermal-yolo/yolo26_workload/yolo26_3inst_icclz1.registry.yaml
kubectl -n intent-lab rollout status deploy/yolo26n-focus
kubectl -n intent-lab rollout status deploy/yolo26n-bg-1
kubectl -n intent-lab rollout status deploy/yolo26n-bg-2
```

若要保留本地 image 路徑，原本的 `.yaml` 仍可繼續使用。

## 7. 驗證

檢查 image 與 pod：

```bash
kubectl -n intent-lab get pods -o wide
kubectl -n intent-lab describe pod <pod-name>
```

檢查 `Image:` 與 `Image ID:` 是否來自 Harbor。

健康檢查：

```bash
kubectl -n intent-lab port-forward deploy/yolo26n-detect 18080:18080
curl http://127.0.0.1:18080/healthz
```

三實例可直接檢查對外的 hostPort：

```bash
curl http://<worker-ip>:18081/healthz
curl http://<worker-ip>:18082/healthz
curl http://<worker-ip>:18083/healthz
```

## 8. 記錄交付資訊

每次正式 rebuild 建議至少保存：

- 使用的 image tag
- digest
- 套用的 manifest 路徑
- 所有 node 的 `registries.yaml` 版本
- Harbor robot account 權限範圍
- 成功 rollout 的時間與操作者

## 9. 回退方式

若 Harbor 路徑暫時失敗，可回退到既有 local image 流程：

1. 改回 `deployment.yaml` 或 `yolo26_3inst_icclz1.yaml`
2. 在目標 worker 手動 build/import `local/yolo26n:0.1`
3. 確認 pod 重新 rollout 成功
