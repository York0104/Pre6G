# Harbor Rebuild Steps

本文件描述如何在新的 k3s cluster 上重建 YOLO26 registry workflow。建議先完成 Harbor pull path，再決定是否啟用 Kaniko build。

## 0. 前置條件

- Harbor 已可從所有 k3s node 連線。
- 每個 GPU node 已具備 NVIDIA driver 與可用的 container runtime。
- `intent-lab` namespace 已存在。
- 目前正式支援的 YOLO image tag 為 `0.1`。
- `intent-lab` 的歷史匯出快照仍可見 `0.5`，但這不再是目前建議的 rebuild 標準。
- 2026-06-04 實測顯示，在本環境中應直接使用 `HTTPS:8088 + 自簽 CA`；先前 `HTTP:8088` 路徑在 `k3s v1.35.4+k3s1 / containerd v2.2.3-k3s1` 上容易卡在 `HTTPS client`。

## 1. 建立 Harbor project 與帳號

建議至少建立：

- project: `pre6g`
- repo: `pre6g/yolo26n`
- robot account: pull / push 分離，或至少一組可先完成 PoC

正式實驗請額外記錄 digest：

```text
harbor.iccl.local:8088/pre6g/yolo26n@sha256:<digest>
```

## 2. 將 Harbor 切換為 HTTPS 8088

### 2.1 產生 Harbor CA 與 server cert

在 Harbor host 上至少準備：

- `/opt/harbor/certs/harbor-ca.crt`
- `/opt/harbor/certs/harbor-ca.key`
- `/opt/harbor/certs/harbor.iccl.local.crt`
- `/opt/harbor/certs/harbor.iccl.local.key`

憑證 SAN 至少包含：

- `DNS: harbor.iccl.local`
- `IP: 140.113.179.9`

### 2.2 修改 `harbor.yml`

`/opt/harbor/harbor/harbor.yml` 的核心設定應為：

```yaml
hostname: harbor.iccl.local

# http:
#   port: 80

https:
  port: 8088
  certificate: /opt/harbor/certs/harbor.iccl.local.crt
  private_key: /opt/harbor/certs/harbor.iccl.local.key
  strong_ssl_ciphers: false
```

然後重新套用：

```bash
cd /opt/harbor/harbor
sudo ./install.sh
```

### 2.3 驗證 Harbor HTTPS

```bash
curl -kI https://harbor.iccl.local:8088
```

應回 `HTTP/1.1 200 OK`。

## 3. 設定每個 k3s node 的 private registry

每個會 pull Harbor image 的 node 都要：

1. 能解析 `harbor.iccl.local`
2. 安裝 Harbor CA 到 system trust store
3. 安裝 Harbor CA 到 `k3s` 使用的位置
4. 寫入 `registries.yaml`

### 3.1 安裝 Harbor CA

```bash
echo '140.113.179.9 harbor.iccl.local' | sudo tee -a /etc/hosts
sudo mkdir -p /usr/local/share/ca-certificates/pre6g
sudo mkdir -p /etc/rancher/k3s/certs
sudo cp harbor-ca.crt /usr/local/share/ca-certificates/pre6g/harbor-ca.crt
sudo cp harbor-ca.crt /etc/rancher/k3s/certs/harbor-ca.crt
sudo update-ca-certificates
```

### 3.2 寫 `registries.yaml`

可先複製樣板：

```bash
sudo mkdir -p /etc/rancher/k3s
sudo cp k3s-migration-bundle-sanitized/registry/harbor-registries.yaml.example /etc/rancher/k3s/registries.yaml
```

或直接寫成：

```bash
sudo tee /etc/rancher/k3s/registries.yaml > /dev/null <<'EOF'
mirrors:
  "harbor.iccl.local:8088":
    endpoint:
      - "https://harbor.iccl.local:8088"

configs:
  "harbor.iccl.local:8088":
    auth:
      username: "robot$pre6g+pre6g-pull"
      password: "<HARBOR_ROBOT_TOKEN>"
    tls:
      ca_file: /etc/rancher/k3s/certs/harbor-ca.crt
EOF
```

套用後重啟：

```bash
sudo systemctl restart k3s
sudo systemctl restart k3s-agent
```

若某些 node 不是 server 或不是 agent，只需重啟對應服務。

## 4. 建立 namespace 與 secrets

套用 namespace：

```bash
kubectl apply -f k3s-migration-bundle-sanitized/registry/image-build.namespace.yaml
```

建立 secret 有兩種方式。

方式 A：直接用指令建立：

```bash
kubectl -n image-build create secret docker-registry harbor-push-secret \
  --docker-server=harbor.iccl.local:8088 \
  --docker-username='<HARBOR_ROBOT_ACCOUNT>' \
  --docker-password='<HARBOR_ROBOT_TOKEN>' \
  --docker-email='noreply@pre6g.local'

kubectl -n intent-lab create secret docker-registry harbor-pull-secret \
  --docker-server=harbor.iccl.local:8088 \
  --docker-username='<HARBOR_ROBOT_ACCOUNT>' \
  --docker-password='<HARBOR_ROBOT_TOKEN>' \
  --docker-email='noreply@pre6g.local'
```

方式 B：先編輯 `imagepullsecret.example.yaml` 再 `kubectl apply -f`。

## 5. 建立 image 並 push 到 Harbor

先在 Harbor host 補 Docker insecure registry，這一步只用於 `docker build/tag/push`，不代表 k3s node 要走 HTTP：

`/etc/docker/daemon.json`

```json
{
  "insecure-registries": [
    "140.113.179.9:8088",
    "harbor.iccl.local:8088"
  ]
}
```

套用：

```bash
sudo systemctl restart docker
docker info | grep -A5 "Insecure Registries"
```

### 5.1 手動 build + push

實際驗證成功的最短步驟：

```bash
cd autoscale-source-split/02-experiment-layer/yolo26_workload
docker build -t local/yolo26n:0.1 .
docker tag local/yolo26n:0.1 harbor.iccl.local:8088/pre6g/yolo26n:0.1
docker login harbor.iccl.local:8088 -u 'robot$pre6g+pre6g-push' -p '<HARBOR_PUSH_ROBOT_TOKEN>'
docker push harbor.iccl.local:8088/pre6g/yolo26n:0.1
```

### 5.2 Kaniko build job

如需 cluster-side build，再走：

```bash
kubectl apply -f k3s-migration-bundle-sanitized/registry/kaniko-yolo26-build-job.yaml
kubectl -n image-build logs -f job/kaniko-build-yolo26n
```

## 6. 先驗證 worker 可以 pull Harbor image

### 6.1 理想路徑

```bash
sudo crictl pull harbor.iccl.local:8088/pre6g/yolo26n:0.1
```

### 6.2 本次環境實際成功的 fallback

在 `icclz1` 上，`crictl pull` 仍可能卡在 `no basic auth credentials`，但以下指令已實測成功：

```bash
sudo k3s ctr images pull \
  --user 'robot$pre6g+pre6g-pull:<HARBOR_PULL_ROBOT_TOKEN>' \
  harbor.iccl.local:8088/pre6g/yolo26n:0.1
```

確認 image 已存在：

```bash
sudo k3s ctr images ls | grep 'harbor.iccl.local:8088/pre6g/yolo26n:0.1'
```

若走這個 fallback，後續 workload manifest 需維持 `imagePullPolicy: IfNotPresent`。

## 7. 部署 registry 版 YOLO

單實例：

```bash
kubectl apply -f k3s-migration-bundle-sanitized/thermal-yolo/yolo26_workload/deployment.registry.yaml
kubectl -n intent-lab rollout status deploy/yolo26n-detect
```

三實例：

```bash
sed 's/REPLACE_GPU_NODE/icclz1/g' \
  k3s-migration-bundle-sanitized/thermal-yolo/yolo26_workload/yolo26_3inst_icclz1.registry.yaml \
  | kubectl apply -f -

kubectl -n intent-lab rollout status deploy/yolo26n-focus
kubectl -n intent-lab rollout status deploy/yolo26n-bg-1
kubectl -n intent-lab rollout status deploy/yolo26n-bg-2
```

若要保留本地 image 路徑，原本的 `.yaml` 仍可繼續使用。

若三實例先前已因 pull 失敗而建立了卡住的 pod，可在 image 已預載後強制重建：

```bash
kubectl -n intent-lab delete pod -l app=yolo26n
kubectl -n intent-lab get pods -o wide -w
```

## 8. 驗證

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

2026-06-04 本輪成功狀態：

- `yolo26n-focus` `1/1 Running`
- `yolo26n-bg-1` `1/1 Running`
- `yolo26n-bg-2` `1/1 Running`

## 9. 記錄交付資訊

每次正式 rebuild 建議至少保存：

- 使用的 image tag
- digest
- 套用的 manifest 路徑
- 所有 node 的 `registries.yaml` 版本
- Harbor robot account 權限範圍
- 成功 rollout 的時間與操作者

## 10. 已知殘餘問題

- 在本環境下，`icclz1` 的 `sudo crictl pull harbor.iccl.local:8088/pre6g/yolo26n:0.1` 仍可能報 `no basic auth credentials`
- 但 `sudo k3s ctr images pull --user ...` 已成功，且 registry workload 已實際 `Running`
- 因此 Harbor 路徑可視為「實務上完成」，但後續若要把 `crictl pull` 也完全收斂，仍需再追 `k3s/containerd` 自動 auth 行為

## 11. 回退方式

若 Harbor 路徑暫時失敗，可回退到既有 local image 流程：

1. 改回 `deployment.yaml` 或 `yolo26_3inst_icclz1.yaml`
2. 在目標 worker 手動 build/import `local/yolo26n:0.1`
3. 確認 pod 重新 rollout 成功
