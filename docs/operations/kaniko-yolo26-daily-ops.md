# Kaniko YOLO26 Daily Ops

## Purpose

這份文件給日常操作使用，涵蓋：

- build
- rollout
- health check
- rollback

如果你要從零重建整套 Harbor / Kaniko / K3s 路線，請看：

- [kaniko-yolo26-build-rebuild.md](/home/icclz2/Pre6G/docs/rebuild/kaniko-yolo26-build-rebuild.md)


## Daily Build Decision

- `build_mode=none`
  - 直接 rollout 既有 Harbor image
- `build_mode=app`
  - 日常主線
  - 只重建 app layer
- `build_mode=base`
  - 只有 CUDA / torch / requirements / model 變更時才跑
- `build_mode=full`
  - 只作 validation / benchmark
  - 不作日常主線

## App Build 操作

### 1. 產生 tag

```bash
cd /home/icclz2/Pre6G
export IMAGE_TAG="kaniko-app-$(date +%Y%m%d-%H%M)"
echo "$IMAGE_TAG"
```

### 2. render app build job

```bash
sed "s/REPLACE_IMAGE_TAG/${IMAGE_TAG}/g" \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-app-build-job.yaml \
  > /tmp/kaniko-yolo26-app-build-job.generated.yaml
```

### 3. dry-run

```bash
kubectl create --dry-run=client \
  -f /tmp/kaniko-yolo26-app-build-job.generated.yaml \
  -o yaml >/tmp/kaniko-yolo26-app-build-job.dryrun.yaml
```

### 4. apply job

```bash
kubectl -n image-build delete job kaniko-build-yolo26-app --ignore-not-found
kubectl apply -f /tmp/kaniko-yolo26-app-build-job.generated.yaml
```

### 5. watch logs

```bash
kubectl -n image-build get pods -l job-name=kaniko-build-yolo26-app -o wide
kubectl -n image-build logs -f job/kaniko-build-yolo26-app
kubectl -n image-build get job,pod -l job-name=kaniko-build-yolo26-app -o wide
```

成功判準：

- job 為 `Complete 1/1`
- Harbor 出現新 tag

## Runtime Pull 驗證

先驗 runtime side 能拉到新 image：

```bash
sudo crictl pull harbor.iccl.local:8088/pre6g/yolo26n:${IMAGE_TAG}
```

如果 `crictl` auth 還不穩，可用既有 fallback：

```bash
sudo k3s ctr images pull \
  --user 'robot$pre6g+pre6g-pull:<HARBOR_PULL_TOKEN>' \
  harbor.iccl.local:8088/pre6g/yolo26n:${IMAGE_TAG}
```

不要把真實 token 寫進 repo 或文件。

## Rollout 到 `intent-lab`

### 1. 設定 image

```bash
export NEW_IMAGE="harbor.iccl.local:8088/pre6g/yolo26n:${IMAGE_TAG}"
echo "$NEW_IMAGE"
```

### 2. 更新三個 deployment

container name 一律是 `yolo26`。

```bash
kubectl -n intent-lab set image deployment/yolo26n-focus yolo26=${NEW_IMAGE}
kubectl -n intent-lab set image deployment/yolo26n-bg-1 yolo26=${NEW_IMAGE}
kubectl -n intent-lab set image deployment/yolo26n-bg-2 yolo26=${NEW_IMAGE}
```

### 3. 檢查 rollout

```bash
kubectl -n intent-lab rollout status deployment/yolo26n-focus
kubectl -n intent-lab rollout status deployment/yolo26n-bg-1
kubectl -n intent-lab rollout status deployment/yolo26n-bg-2
kubectl -n intent-lab get deploy
kubectl -n intent-lab get pods -o wide
```

## Health Check

```bash
curl -fsS http://140.113.179.6:18081/healthz
curl -fsS http://140.113.179.6:18082/healthz
curl -fsS http://140.113.179.6:18083/healthz
```

成功判準：

- `18081` `focus` 成功
- `18082` `background-1` 成功
- `18083` `background-2` 成功

## Rollback

切回已知穩定 image，例如：

```bash
export ROLLBACK_IMAGE="harbor.iccl.local:8088/pre6g/yolo26n:0.1"

kubectl -n intent-lab set image deployment/yolo26n-focus yolo26=${ROLLBACK_IMAGE}
kubectl -n intent-lab set image deployment/yolo26n-bg-1 yolo26=${ROLLBACK_IMAGE}
kubectl -n intent-lab set image deployment/yolo26n-bg-2 yolo26=${ROLLBACK_IMAGE}

kubectl -n intent-lab rollout status deployment/yolo26n-focus
kubectl -n intent-lab rollout status deployment/yolo26n-bg-1
kubectl -n intent-lab rollout status deployment/yolo26n-bg-2

curl -fsS http://140.113.179.6:18081/healthz
curl -fsS http://140.113.179.6:18082/healthz
curl -fsS http://140.113.179.6:18083/healthz
```

## When To Rebuild Base

只有以下情況才跑 `base build`：

- CUDA runtime 變更
- `torch` / `torchvision` 版本變更
- `requirements.txt` heavy dependency 變更
- `yolo26m.pt` 或模型版本變更

平常如果只是改：

- `app.py`
- helper `*.py`
- metrics logic
- startup script

不要跑 `base build`，直接走 `build_mode=app`。

## Common Checks

```bash
kubectl -n image-build get jobs
kubectl -n image-build get pods
kubectl -n image-build logs -f job/kaniko-build-yolo26-app
kubectl -n intent-lab get deploy
kubectl -n intent-lab get pods -o wide
```

## Common Troubleshooting

### `ImagePullBackOff`

- 先查：

```bash
kubectl -n intent-lab describe pod <pod-name>
```

- 常見原因：
  - Harbor pull auth 錯
  - `harbor-pull-secret` 沒掛好
  - node trust / x509 問題

### `replicas=0`

- 如果 `bg-1` 沒 pod，先查：

```bash
kubectl -n intent-lab get deploy yolo26n-bg-1 -o yaml | grep -n replicas:
```

- 若 live deployment 被縮成 0，恢復：

```bash
kubectl -n intent-lab scale deployment/yolo26n-bg-1 --replicas=1
kubectl -n intent-lab rollout status deployment/yolo26n-bg-1
```

### `/healthz` 不通

- 先查：

```bash
kubectl -n intent-lab get pods -o wide
kubectl -n intent-lab describe pod -l app=yolo26n
```

- 常見原因：
  - 對應 pod 不在
  - rollout 還沒完成
  - `bg-1` 被縮成 `0 replicas`

### Kaniko job 沒有 `Complete 1/1`

- 先查：

```bash
kubectl -n image-build get job,pod
kubectl -n image-build logs -f job/kaniko-build-yolo26-app
```

- 如果是 `base build`，只在 base 真的需要重建時才跑

### Harbor pull auth / x509 問題

- auth 問題：
  - 檢查 pull account / secret
- x509 問題：
  - 檢查 Harbor CA trust
  - 檢查 node 端 `registries.yaml` 與 CA 安裝

遇到這類問題時，完整重建與修法請回看：

- [kaniko-yolo26-build-rebuild.md](/home/icclz2/Pre6G/docs/rebuild/kaniko-yolo26-build-rebuild.md)

