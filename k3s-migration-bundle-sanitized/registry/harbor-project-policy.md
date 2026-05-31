# Harbor Project Policy

## Project

- project: `pre6g`

## Repository Naming

- `pre6g/yolo26n`
- `pre6g/autoscale-api`
- `pre6g/ap-gateway`
- `pre6g/rfsoc-aggregator`
- `pre6g/vm-aggregator`
- `pre6g/experiment-tools`

## Tag Strategy

建議至少保留三種 tag 類型：

- semantic tag，例如 `0.1`
- experiment tag，例如 `thermal-task3-20260531`
- source tag，例如 `<git-short-sha>`

範例：

```text
harbor.iccl.local/pre6g/yolo26n:0.1
harbor.iccl.local/pre6g/yolo26n:thermal-task3-20260531
harbor.iccl.local/pre6g/yolo26n:a1b2c3d
```

## Digest Recording

正式驗證與交付請一律額外保存 digest：

```text
harbor.iccl.local/pre6g/yolo26n@sha256:<digest>
```

## Access Policy

- build system 使用 push 權限帳號
- runtime workload 使用 pull-only 帳號
- 不要在 repo 中保存 robot token
- 自簽 CA、實際 `registries.yaml`、正式 token 應保存在 private handoff
