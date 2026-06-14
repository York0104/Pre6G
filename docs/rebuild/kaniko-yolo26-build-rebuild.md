# Kaniko YOLO26 Build Rebuild

Date: 2026-06-14  
Workspace: `/home/icclz2/Pre6G`

## Purpose

本文件定義 Pre6G 現階段的 YOLO26 registry build 主線。

結論先寫在前面：

- `full build` 保留，但只作 validation / benchmark path
- 正式日常主線改為 `base/app split`
- 第一版只拆兩層，不先拆三層
- 保留目前已成功的 CUDA runtime 路線

## Current Validation State

截至 2026-06-14，這條線的實機驗證狀態如下：

- `full build` live validation 已通過前置元件驗證
  - Git context clone 正常
  - Harbor DNS 正常
  - Harbor TLS / CA 正常
  - Harbor auth 正常
  - Dockerfile path 正常
- `full build` 目前仍保留在 cluster 內長時間 `Running`
  - 代表主要瓶頸是 heavy image build / final snapshot / upload
  - 不再適合作為日常 build 主線
- `split build` 的 repo 內檔案結構與 job 樣板已完成
- `split build` 曾在第一輪 live run 卡在 `Dockerfile path resolution`
  - 原因是 `Kaniko git context + context-sub-path + custom Dockerfile name` 的組合解析不穩定
  - 已改成 `initContainer clone repo + dir:// context + explicit Dockerfile path`
  - 2026-06-14 新版 live validation 已確認此 blocker 已解除
- `split build` 已正式改成 `initContainer clone repo + dir:// context`
- 2026-06-14 的新版 `base build` live validation 已確認：
  - `clone-repo` 成功
  - `test -f Dockerfile.base` 成功
  - `yolo26_workload` 目錄內容可列出
  - Kaniko 不再出現 `error resolving dockerfile path`
  - Kaniko 已開始執行 `Dockerfile.base`
  - build 已成功跑完整個 `base build` job
- `base image` build job 已 `Complete 1/1`
- `base image` runtime pull 已成功
- `app build` 已成功完成並 push
- `app image` runtime pull 已成功
- `intent-lab` rollout 已成功
- 三個 `/healthz` 已全部成功

## Why Full Build Is Not The Daily Path

2026-06-13 的 live validation 已確認：

- full Kaniko build 已通過 Git context
- 已通過 Harbor DNS
- 已通過 Harbor TLS / CA
- 已通過 Harbor auth
- 已通過正確 Dockerfile path

因此目前問題不是流程錯誤，而是：

- full image 太重
- build 期間要安裝大量 AI 依賴
- build 期間還會下載 `yolo26m.pt`
- final snapshot / Harbor upload 耗時過長

這讓 full build 不適合作為日常 app iteration 主線。

## Build Paths

### Full Build Path

用途：

- validation
- benchmark
- 確認完整 Dockerfile 仍可被 Kaniko build

對應檔案：

- [Dockerfile](/home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile)
- [kaniko-yolo26-build-job.yaml](/home/icclz2/Pre6G/k3s-migration-bundle-sanitized/registry/kaniko-yolo26-build-job.yaml)

特性：

- build 最重
- 主要用來驗證整條 full path
- 不作為日常主線

### Split Build Path

用途：

- 正式日常 build 主線
- 將 heavy dependencies 與 app logic 分離

對應檔案：

- [Dockerfile.base](/home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.base)
- [Dockerfile.app](/home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.app)
- [kaniko-yolo26-base-build-job.yaml](/home/icclz2/Pre6G/k3s-migration-bundle-sanitized/registry/kaniko-yolo26-base-build-job.yaml)
- [kaniko-yolo26-app-build-job.yaml](/home/icclz2/Pre6G/k3s-migration-bundle-sanitized/registry/kaniko-yolo26-app-build-job.yaml)

特性：

- `base image` 偶爾 build
- `app image` 才是日常 Kaniko 主線
- 大幅減少每次改 app logic 時的 build 成本
- 不再依賴 `Kaniko git context + context-sub-path + custom Dockerfile name`

## Build Modes

| build_mode | 用途 | 是否日常主線 | 說明 |
| --- | --- | --- | --- |
| `none` | 直接部署既有 Harbor image | 是 | 不重新 build，直接 rollout 已存在 image |
| `app` | 只 build app layer | 是 | 日常主線，從 `yolo26-base:0.1` 出發 |
| `base` | build heavy base image | 否 | 只在依賴或模型版本變更時執行 |
| `full` | build 完整 image | 否 | 只作 validation / benchmark |

## File Structure

```text
Pre6G/
├── autoscale-source-split/
│   └── 02-experiment-layer/
│       └── yolo26_workload/
│           ├── Dockerfile
│           ├── Dockerfile.base
│           ├── Dockerfile.app
│           ├── app.py
│           ├── startup.app.sh
│           ├── build_and_import_image_to_k3s.sh
│           └── requirements.txt
├── docs/
│   ├── notes/
│   │   └── kaniko-yolo26-build-decision-log.md
│   └── rebuild/
│       └── kaniko-yolo26-build-rebuild.md
└── k3s-migration-bundle-sanitized/
    └── registry/
        ├── image-build.namespace.yaml
        ├── kaniko-yolo26-build-job.yaml
        ├── kaniko-yolo26-base-build-job.yaml
        └── kaniko-yolo26-app-build-job.yaml
```

## Images

### Base Image

- name: `harbor.iccl.local:8088/pre6g/yolo26-base:0.1`
- built from: `Dockerfile.base`
- contains:
  - CUDA runtime
  - Python / pip
  - `torch`
  - `torchvision`
  - requirements-heavy dependencies
  - `yolo26m.pt`

### App Image

- name: `harbor.iccl.local:8088/pre6g/yolo26n:REPLACE_IMAGE_TAG`
- built from: `Dockerfile.app`
- contains:
  - app-layer logic
  - current `*.py` files
  - current `startup*.sh` files
  - `build_and_import_image_to_k3s.sh`

## Common Preconditions

執行前請先確認：

- Harbor 已正式收斂為 `HTTPS:8088 + 自簽 CA`
- Harbor project `pre6g` 已存在
- `image-build` namespace 可建立
- `intent-lab` 已存在
- `harbor-push-secret` 可使用 push robot account 建立
- `harbor-ca` ConfigMap 可由 `/etc/rancher/k3s/certs/harbor-ca.crt` 生成
- split pipeline 相關檔案已經 commit 並 push 到 GitHub `York0104/Pre6G` 的 `k3s-rebuild` branch

## Common Bootstrap

以下步驟適用於 `base` 與 `app` build。

### 1. 切到 repo 根目錄

```bash
cd /home/icclz2/Pre6G
```

Verification:

```bash
pwd
git branch --show-current
git status --short
```

Success criteria:

- `pwd` 顯示 `/home/icclz2/Pre6G`
- branch 顯示 `k3s-rebuild`
- 沒有尚未 push 的 split pipeline 必要檔案

### 2. 建立 build namespace

```bash
kubectl apply -f k3s-migration-bundle-sanitized/registry/image-build.namespace.yaml
```

Verification:

```bash
kubectl get ns image-build
```

Success criteria:

- `image-build` 顯示為 `Active`

### 3. 建立 Harbor push secret

```bash
kubectl -n image-build create secret docker-registry harbor-push-secret \
  --docker-server=harbor.iccl.local:8088 \
  --docker-username='<HARBOR_PUSH_USERNAME>' \
  --docker-password='<HARBOR_PUSH_TOKEN>' \
  --docker-email='noreply@pre6g.local' \
  --dry-run=client -o yaml | kubectl apply -f -
```

Verification:

```bash
kubectl -n image-build get secret harbor-push-secret
kubectl -n image-build get secret harbor-push-secret -o jsonpath='{.type}{"\n"}'
```

Success criteria:

- secret 存在
- type 為 `kubernetes.io/dockerconfigjson`

### 4. 建立 Harbor CA ConfigMap

```bash
kubectl -n image-build create configmap harbor-ca \
  --from-file=harbor-ca.crt=/etc/rancher/k3s/certs/harbor-ca.crt \
  --dry-run=client -o yaml | kubectl apply -f -
```

Verification:

```bash
kubectl -n image-build get configmap harbor-ca
kubectl -n image-build get configmap harbor-ca -o jsonpath='{.data.harbor-ca\.crt}' | head -n 1
```

Success criteria:

- `harbor-ca` 存在
- 內容開頭可看到 PEM header

## Why Split Build Changed To initContainer + dir Context

split build 原本採用：

- `--context=git://github.com/York0104/Pre6G.git#refs/heads/k3s-rebuild`
- `--context-sub-path=autoscale-source-split/02-experiment-layer/yolo26_workload`
- `--dockerfile=Dockerfile.base` 或 `--dockerfile=Dockerfile.app`

實際 live run 失敗於：

- `error resolving dockerfile path: please provide a valid path to a Dockerfile within the build context with --dockerfile`

根因收斂為：

- full build 能過，是因為它使用標準 `Dockerfile`
- split build 使用 `Dockerfile.base` / `Dockerfile.app`
- `Kaniko git context + context-sub-path + custom Dockerfile name` 的組合解析不穩定

因此目前正式做法改為：

- `initContainer` 先 clone repo 到 `emptyDir`
- Kaniko 改用 `dir://` 指向明確本地目錄
- `--dockerfile` 改成明確絕對路徑

這會增加少量 YAML，但換來：

- build context 明確
- clone 成敗可獨立驗證
- Dockerfile 是否存在可在 Kaniko 啟動前先驗證
- path issue 與 Harbor / TLS / auth 問題可明確分離

## Base Image Build

### Dockerfile Summary

[Dockerfile.base](/home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.base)

重點：

- 保留 `nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04`
- 不改掉現有成功的 CUDA 路線
- 模型短期先放進 base image

### Job Summary

[kaniko-yolo26-base-build-job.yaml](/home/icclz2/Pre6G/k3s-migration-bundle-sanitized/registry/kaniko-yolo26-base-build-job.yaml)

重點：

- namespace：`image-build`
- `initContainer` 先 clone `York0104/Pre6G`
- context：`dir:///workspace/src/autoscale-source-split/02-experiment-layer/yolo26_workload`
- dockerfile：`/workspace/src/autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.base`
- destination：`harbor.iccl.local:8088/pre6g/yolo26-base:0.1`
- `hostAliases` 保留 `harbor.iccl.local -> 140.113.179.9`

修法重點：

- 不再使用 `Kaniko git context + context-sub-path`
- clone 與 build context 明確分離
- 若失敗，可先看 initContainer log 判斷 repo / path 問題

### Build Commands

```bash
cd /home/icclz2/Pre6G
kubectl create --dry-run=client \
  -f k3s-migration-bundle-sanitized/registry/kaniko-yolo26-base-build-job.yaml \
  -o yaml >/tmp/kaniko-yolo26-base-build-job.dryrun.yaml

kubectl -n image-build delete job kaniko-build-yolo26-base --ignore-not-found
kubectl apply -f k3s-migration-bundle-sanitized/registry/kaniko-yolo26-base-build-job.yaml
```

Verification:

```bash
kubectl -n image-build get job kaniko-build-yolo26-base
kubectl -n image-build get pods -l job-name=kaniko-build-yolo26-base -o wide
kubectl -n image-build logs job/kaniko-build-yolo26-base -c clone-repo
kubectl -n image-build logs -f job/kaniko-build-yolo26-base
```

Success criteria:

- job 成功建立
- `clone-repo` log 顯示 repo clone 成功
- `clone-repo` log 中可看到 `yolo26_workload` 目錄內容
- log 無 `x509` / `401 Unauthorized` / `no such host`
- log 不再出現 `error resolving dockerfile path`
- log 顯示 push 成功

已確認達成：

- `job 成功建立`
- `clone-repo` 成功
- `yolo26_workload` 目錄內容可見
- 不再出現 `error resolving dockerfile path`
- 已開始執行真正的 `Dockerfile.base`
- `kaniko-build-yolo26-base` 最終狀態為 `Complete 1/1`
- `sudo crictl pull harbor.iccl.local:8088/pre6g/yolo26-base:0.1` 成功
- runtime digest readback:
  - `sha256:290d8e363fd1d3f90063a3c70e0337ed969f2c108a80d6af96dfbabb7df55991`

待補最終確認：

- Harbor 出現 `harbor.iccl.local:8088/pre6g/yolo26-base:0.1`
- 若需要 repository tag list 證據，再補 Harbor API readback

## App Image Build

### Dockerfile Summary

[Dockerfile.app](/home/icclz2/Pre6G/autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.app)

重點：

- `FROM harbor.iccl.local:8088/pre6g/yolo26-base:0.1`
- 不大搬現有目錄
- 會 COPY 目前目錄下的 `*.py` 與 `startup*.sh`
- 不只 COPY `app.py`
- `EXPOSE 18080`

### Job Summary

[kaniko-yolo26-app-build-job.yaml](/home/icclz2/Pre6G/k3s-migration-bundle-sanitized/registry/kaniko-yolo26-app-build-job.yaml)

重點：

- `initContainer` 先 clone `York0104/Pre6G`
- context：`dir:///workspace/src/autoscale-source-split/02-experiment-layer/yolo26_workload`
- dockerfile：`/workspace/src/autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.app`
- destination：`harbor.iccl.local:8088/pre6g/yolo26n:REPLACE_IMAGE_TAG`

### Build Commands

```bash
cd /home/icclz2/Pre6G
export IMAGE_TAG="kaniko-$(date +%Y%m%d-%H%M)"

sed "s/REPLACE_IMAGE_TAG/${IMAGE_TAG}/g" \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-app-build-job.yaml \
  > /tmp/kaniko-yolo26-app-build-job.generated.yaml

kubectl create --dry-run=client \
  -f /tmp/kaniko-yolo26-app-build-job.generated.yaml \
  -o yaml >/tmp/kaniko-yolo26-app-build-job.dryrun.yaml

kubectl -n image-build delete job kaniko-build-yolo26-app --ignore-not-found
kubectl apply -f /tmp/kaniko-yolo26-app-build-job.generated.yaml
```

Verification:

```bash
kubectl -n image-build get job kaniko-build-yolo26-app
kubectl -n image-build get pods -l job-name=kaniko-build-yolo26-app -o wide
kubectl -n image-build logs job/kaniko-build-yolo26-app -c clone-repo
kubectl -n image-build logs -f job/kaniko-build-yolo26-app
```

Success criteria:

- job 成功建立
- `clone-repo` log 顯示 repo clone 成功
- log 不再出現 `error resolving dockerfile path`
- log 顯示 push 成功
- Harbor 出現 `harbor.iccl.local:8088/pre6g/yolo26n:${IMAGE_TAG}`

目前狀態：

- 已完成
- 已驗證：
  - `clone-repo` 成功
  - `FROM harbor.iccl.local:8088/pre6g/yolo26-base:0.1` 成功
  - push 成功
  - job 最終 `Complete 1/1`
  - runtime pull 成功

實際驗證 tag：

- `kaniko-app-20260614-2220`

實際 push digest：

- `sha256:dfee5f43bd6a500cac056ee20359e78de0878c207df8644179e5f554f66ba75b`

runtime pull readback digest：

- `sha256:fbc8d5750f5d56423db748e50045a8600a5f26cfd0c2a60b93123d941b4e51fa`

## Harbor Tag Verification

### Base Image

```bash
curl -sk -u '<HARBOR_PUSH_USERNAME>:<HARBOR_PUSH_TOKEN>' \
  https://harbor.iccl.local:8088/v2/pre6g/yolo26-base/tags/list
```

Success criteria:

- `0.1` 出現在 tag list

目前狀態：

- `base build job` 已完成
- runtime pull readback 已成功
- 若需要 API 證據，可再補 Harbor tag list 輸出

### App Image

```bash
curl -sk -u '<HARBOR_PUSH_USERNAME>:<HARBOR_PUSH_TOKEN>' \
  https://harbor.iccl.local:8088/v2/pre6g/yolo26n/tags/list
```

Success criteria:

- `${IMAGE_TAG}` 出現在 tag list

## Harbor Pull Verification

base/app image push 成功後，先驗 Harbor registry 可被 runtime side 讀到。

### Base Image

```bash
sudo crictl pull harbor.iccl.local:8088/pre6g/yolo26-base:0.1
```

Success criteria:

- pull 成功
- 不出現 `x509`、`401 Unauthorized`、`no basic auth credentials`

已確認達成：

- `sudo crictl pull harbor.iccl.local:8088/pre6g/yolo26-base:0.1` 成功

### App Image

```bash
sudo crictl pull harbor.iccl.local:8088/pre6g/yolo26n:${IMAGE_TAG}
```

Success criteria:

- pull 成功
- runtime node 能讀到新 tag

已確認達成：

- `sudo crictl pull harbor.iccl.local:8088/pre6g/yolo26n:kaniko-app-20260614-2220` 成功

## Rollout To intent-lab

### 1. 設定 image

```bash
export NEW_IMAGE="harbor.iccl.local:8088/pre6g/yolo26n:${IMAGE_TAG}"
echo "${NEW_IMAGE}"
```

### 2. 更新三個 deployments

```bash
kubectl -n intent-lab set image deployment/yolo26n-focus yolo26=${NEW_IMAGE}
kubectl -n intent-lab set image deployment/yolo26n-bg-1 yolo26=${NEW_IMAGE}
kubectl -n intent-lab set image deployment/yolo26n-bg-2 yolo26=${NEW_IMAGE}
```

Verification:

```bash
kubectl -n intent-lab get deploy \
  -o custom-columns=NAME:.metadata.name,IMAGE:.spec.template.spec.containers[*].image
```

Success criteria:

- 三個 deployment 都顯示 `${NEW_IMAGE}`

### 3. 觀察 rollout

```bash
kubectl -n intent-lab rollout status deployment/yolo26n-focus
kubectl -n intent-lab rollout status deployment/yolo26n-bg-1
kubectl -n intent-lab rollout status deployment/yolo26n-bg-2
kubectl -n intent-lab get pods -o wide
```

Success criteria:

- 三個 rollout 全部完成
- 三個 pod 最後都 `1/1 Running`

已確認達成：

- `yolo26n-focus` rollout 成功
- `yolo26n-bg-1` rollout 成功
- `yolo26n-bg-2` rollout 成功
- 最終三個 pods 皆為 `1/1 Running`

## /healthz Verification

```bash
curl -fsS http://140.113.179.6:18081/healthz
curl -fsS http://140.113.179.6:18082/healthz
curl -fsS http://140.113.179.6:18083/healthz
```

Success criteria:

- 三個 `/healthz` 都回傳成功

已確認達成：

- `18081` `focus` 成功
- `18082` `background-1` 成功
- `18083` `background-2` 成功

## Rollback

若新 app image rollout 後有問題，直接切回已知穩定版本。

```bash
export ROLLBACK_IMAGE="harbor.iccl.local:8088/pre6g/yolo26n:0.1"
kubectl -n intent-lab set image deployment/yolo26n-focus yolo26=${ROLLBACK_IMAGE}
kubectl -n intent-lab set image deployment/yolo26n-bg-1 yolo26=${ROLLBACK_IMAGE}
kubectl -n intent-lab set image deployment/yolo26n-bg-2 yolo26=${ROLLBACK_IMAGE}
```

Verification:

```bash
kubectl -n intent-lab rollout status deployment/yolo26n-focus
kubectl -n intent-lab rollout status deployment/yolo26n-bg-1
kubectl -n intent-lab rollout status deployment/yolo26n-bg-2
```

Success criteria:

- 三個 rollout 都回到已知穩定 image

## Cleanup

### 刪除 base build job

```bash
kubectl -n image-build delete job kaniko-build-yolo26-base --ignore-not-found
```

### 刪除 app build job

```bash
kubectl -n image-build delete job kaniko-build-yolo26-app --ignore-not-found
```

### 刪除 full validation job

```bash
kubectl -n image-build delete job kaniko-build-yolo26n --ignore-not-found
```

Verification:

```bash
kubectl -n image-build get jobs
```

Success criteria:

- 已刪除不再需要的 job

## Security Notes

- 不要把 Harbor 真實 token、password、private key 寫進 repo
- `harbor-push-secret` 與 `harbor-ca` 應由 cluster 內資源管理
- Harbor 正式主線使用 `HTTPS:8088 + 自簽 CA`
- `hostAliases` 只是目前 cluster DNS 尚未補齊時的務實做法
- 若未來 cluster DNS 已可解析 `harbor.iccl.local`，可再評估移除 `hostAliases`

## Troubleshooting

只保留 `Symptom / Root cause / Correct fix / Verification`

### Symptom

Kaniko log 出現 `x509: certificate signed by unknown authority`

### Root cause

- `harbor-ca` 沒掛進 pod
- `--registry-certificate` 路徑錯

### Correct fix

- 確認 `harbor-ca` ConfigMap 存在
- 確認 job 保留：
  - `--registry-certificate=harbor.iccl.local:8088=/kaniko/certs/harbor-ca.crt`
  - `/kaniko/certs` volume mount

### Verification

```bash
kubectl -n image-build get configmap harbor-ca
kubectl -n image-build logs job/kaniko-build-yolo26-base
kubectl -n image-build logs job/kaniko-build-yolo26-app
```

### Symptom

Kaniko log 出現 `401 Unauthorized`

### Root cause

- push account / token 錯
- push account 沒有 `pre6g` project 寫入權限

### Correct fix

重建 `harbor-push-secret`，並確認使用的是 push account。

### Verification

```bash
kubectl -n image-build get secret harbor-push-secret
kubectl -n image-build logs job/kaniko-build-yolo26-base
kubectl -n image-build logs job/kaniko-build-yolo26-app
```

### Symptom

Kaniko log 出現 `lookup harbor.iccl.local ... no such host`

### Root cause

- cluster DNS 尚未提供 `harbor.iccl.local`

### Correct fix

保留：

```yaml
hostAliases:
  - ip: "140.113.179.9"
    hostnames:
      - "harbor.iccl.local"
```

### Verification

```bash
grep -n 'hostAliases\|harbor.iccl.local\|140.113.179.9' \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-base-build-job.yaml
grep -n 'hostAliases\|harbor.iccl.local\|140.113.179.9' \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-app-build-job.yaml
```

### Symptom

full build job 長時間停留在 `Running`

### Root cause

- full image 太重
- heavy dependencies、model download、final snapshot、large-image upload 耗時過長

### Correct fix

- 不把 full build 作為日常主線
- 將正式主線切到 `base/app split`

### Verification

```bash
kubectl -n image-build logs job/kaniko-build-yolo26n
kubectl -n image-build get job kaniko-build-yolo26n -o wide
```

### Symptom

`yolo26n-bg-1` rollout 看似成功，但 `kubectl get pods -l app=yolo26n` 只看到 `focus` 與 `bg-2`，而 `curl http://140.113.179.6:18082/healthz` 連不到

### Root cause

- live deployment `yolo26n-bg-1` 的 `spec.replicas` 被設成 `0`
- 因此 K8s 沒有建立任何 `bg-1` pod

### Correct fix

將 `bg-1` 明確恢復為 1 個 replica：

```bash
kubectl -n intent-lab scale deployment/yolo26n-bg-1 --replicas=1
kubectl -n intent-lab rollout status deployment/yolo26n-bg-1
```

### Verification

```bash
kubectl -n intent-lab get deploy yolo26n-bg-1
kubectl -n intent-lab get pods -l app=yolo26n -o wide
curl -fsS http://140.113.179.6:18082/healthz
```

Success criteria:

- `yolo26n-bg-1` 不再是 `0/0`
- `bg-1` pod 變成 `1/1 Running`
- `18082` `/healthz` 回傳成功

### Symptom

Kaniko log 出現 `Dockerfile not found`

### Root cause

- `context-sub-path` 錯
- `dockerfile` 參數錯
- Kaniko 在 `git context + context-sub-path + custom Dockerfile filename` 這組合下，未正確解析 split pipeline 的 Dockerfile 路徑

### Correct fix

不要再繼續微調下列舊作法：

- `--dockerfile=Dockerfile.base`
- `--dockerfile=autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.base`
- `--dockerfile=/workspace/Dockerfile.base`

改用：

- `initContainer` clone repo 到 `/workspace/src`
- `--context=dir:///workspace/src/autoscale-source-split/02-experiment-layer/yolo26_workload`
- `--dockerfile=/workspace/src/autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.base`
  或
- `--dockerfile=/workspace/src/autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.app`

### Verification

```bash
grep -n -- 'dir:///workspace/src' \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-base-build-job.yaml \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-app-build-job.yaml
grep -n -- 'clone-repo\\|Dockerfile.base\\|Dockerfile.app' \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-base-build-job.yaml \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-app-build-job.yaml
kubectl -n image-build logs job/kaniko-build-yolo26-base --tail=120
```

Success criteria:

- 不再出現 `error resolving dockerfile path`
- Kaniko 開始進入真正的 build stage，而不是 clone 後立即退出
- `clone-repo` container 能先證明 Dockerfile 實際存在

### Symptom

`clone-repo` initContainer 只有顯示 `Cloning into '/workspace/src'...` 後就失敗，且 pod `describe` 顯示 `Exit Code: 1`

### Root cause

- GitHub 上的 `k3s-rebuild` branch 還沒有 `Dockerfile.base` / `Dockerfile.app` / 相關新檔
- 本機檔案只存在於工作樹，尚未 commit / push

### Correct fix

- 先將 split pipeline 相關檔案 commit 到本機 branch
- 再 push 到 `origin/k3s-rebuild`
- 確保遠端 branch 真的包含：
  - `autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.base`
  - `autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.app`
  - `k3s-migration-bundle-sanitized/registry/kaniko-yolo26-base-build-job.yaml`
  - `k3s-migration-bundle-sanitized/registry/kaniko-yolo26-app-build-job.yaml`

### Verification

```bash
git status --short \
  autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.base \
  autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.app \
  autoscale-source-split/02-experiment-layer/yolo26_workload/startup.app.sh \
  docs/rebuild/kaniko-yolo26-build-rebuild.md \
  docs/notes/kaniko-yolo26-build-decision-log.md \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-base-build-job.yaml \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-app-build-job.yaml
git ls-files \
  autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.base \
  autoscale-source-split/02-experiment-layer/yolo26_workload/Dockerfile.app \
  autoscale-source-split/02-experiment-layer/yolo26_workload/startup.app.sh \
  docs/rebuild/kaniko-yolo26-build-rebuild.md \
  docs/notes/kaniko-yolo26-build-decision-log.md \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-base-build-job.yaml \
  k3s-migration-bundle-sanitized/registry/kaniko-yolo26-app-build-job.yaml
```

Success criteria:

- 這些檔案不再顯示 `??`
- `git ls-files` 可列出這些路徑

## Live Validation Summary

2026-06-13 的 full build live validation 已證明：

- full Kaniko path 的前置元件基本可用
- 主問題是 full image 過重

因此目前正式建議是：

- `full build`：保留作 validation / benchmark
- `base/app split`：作為 official pipeline

但請務必注意：

- `official pipeline` 指的是架構主線，不代表 2026-06-14 已全部 live 完成
- 目前 split pipeline 已完成的內容是：
  - manifests：已改為 `initContainer clone + dir:// context`
  - Dockerfiles：已補齊
  - rebuild guide：已更新
  - decision log：已新增
  - `base build`：成功
  - `app build`：成功
  - runtime pull：成功
  - rollout：成功
  - `/healthz`：成功
- 2026-06-14 的 split pipeline live validation 已最終驗通：
  - `clone-repo` 成功
  - `Dockerfile.base` / `Dockerfile.app` 路徑已被正確讀取
  - `kaniko-build-yolo26-base` 最終 `Complete 1/1`
  - `kaniko-build-yolo26-app` 最終 `Complete 1/1`
  - 舊的 Dockerfile path blocker 已確認解除
  - `base` 與 `app` image 均已可被 runtime side `crictl pull`
  - 三個 runtime service 最終均可通過 `/healthz`
- 已知唯一 runtime 注意事項：
  - 若 `yolo26n-bg-1` live deployment 被縮成 `replicas: 0`，需先手動恢復成 1
