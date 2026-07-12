# Pre6G config

這個目錄是 `Pre6G` 專案的**設定檔與常用 manifests 入口**。

用途很單純：

- 把 repo 內常用、可版控的設定集中成較好找的入口
- 把與 `Pre6G` 執行直接相關、但位於 repo 外的私有設定也整理成入口
- 讓你之後找 `.service`、`.env.example`、YAML、私有 runtime 設定時，不用再到專案各層目錄逐一翻找

## 目錄結構

```text
config/
├── collector/
├── dashboard/
├── env-examples/
├── manifests/
├── private-runtime/
├── registry/
├── systemd/
└── README.md
```

## 分類說明

### `systemd/`

放可公開版控的 service 設定入口。

目前內容主要是：

- `ap-gateway.service`
- `ap-snmp-gateway.service`
- `autoscale-api.service`

適合找：

- host-side service 定義
- 要對照 systemd 啟動方式時

### `env-examples/`

放可公開版控的 env 範例檔入口。

目前內容主要是：

- `ap-gateway.env.example`
- `ap-snmp-gateway.env.example`
- `autoscale-api.env.example`

適合找：

- 哪些環境變數需要配置
- 新機重建時的模板

補充：

- `autoscale-api.env.example` 已於 `2026-06-24` 補上 `PRE6G_EXPERIMENT_*`，供 `Fan-Cycle Experiment` / `YOLO demo` runtime 使用

### `dashboard/`

放 dashboard 相關公開設定範例入口。

目前內容主要是：

- `cluster-dashboard.env.example`

適合找：

- 前端 `.env` 應該長什麼樣
- dashboard build-time 公開設定模板

若要找這次 `k3s` live dashboard / API 的公開部署文檔，請直接看：

- `autoscale-source-split/03-shared-api-dashboard/deploy/k3s/README.md`
- `autoscale-source-split/03-shared-api-dashboard/deploy/k3s/live-hostpath/README.md`

### `collector/`

放 shareable collector 交付包的公開設定範例入口。

目前內容主要是：

- `full-metrics-api-collector.env.example`

適合找：

- 對外交付時要提供哪些基本設定欄位

### `registry/`

放 Harbor / registry 相關公開設定範例入口。

目前內容主要是：

- `harbor-registries.yaml.example`

適合找：

- registry 範例設定
- Harbor 重建時的公開樣板

### `manifests/`

放常用 YAML manifests 入口，目前分成三類：

#### `manifests/monitoring/`

放 `monitoring-rebuild/` 主線重建用的 YAML。

例如：

- `10-victoria-metrics.yaml`
- `20-vmagent.yaml`
- `55-netdata.yaml`

#### `manifests/experiment/`

放 `02-experiment-layer` 常用 workload / GPU sharing / saturation YAML。

例如：

- `deployment.yaml`
- `deployment.registry.yaml`
- `yolo26_3inst_icclz1.current.yaml`
- `yolo26_task3_saturation.yaml`

#### `manifests/bundle/`

放 `k3s-migration-bundle-sanitized/` 中較常引用的 YAML。

例如：

- `image-build.namespace.yaml`
- `kaniko-yolo26-build-job.yaml`
- `vm-aggregator-job.incluster.yaml`

### `private-runtime/`

放 repo 外、但和 `Pre6G` 執行直接相關的私有設定入口。

這一層是本機導向的，不是公開可攜設定。

目前分成：

- `private-runtime/api/`
- `private-runtime/ssh/`
- `private-runtime/systemd-user/`
- `private-runtime/harbor/`
- `private-runtime/k3s/`

適合找：

- live API token / runtime env
- SSH key / SSH config
- Harbor 私有資產
- k3s live config

目前已確認與本次 dashboard / API 落地直接相關的私有入口包括：

- `private-runtime/api/autoscale-api.env`
- `private-runtime/api/cluster-dashboard.env`
- `private-runtime/api/monitoring-runtime.host.env`
- `private-runtime/systemd-user/pre6g-autoscale-api.service`
- `private-runtime/systemd-user/pre6g-cluster-dashboard.service`
- `private-runtime/harbor/assets`
- `private-runtime/k3s/config`

其中：

- `private-runtime/api/autoscale-api.env` 也是目前 `Fan-Cycle Experiment` 真實 runtime 值的建議入口

## 存放形式

這個目錄中的內容以兩種形式存在：

1. 指向 repo 內原始檔的軟連結
2. 指向 `pre6g-private/` 的軟連結

也就是說，`config/` 本身主要是**入口層**，不是每份設定檔的唯一實體存放位置。

## Canonical Boundary

- `config/manifests/monitoring/` 指向 `monitoring-rebuild/`，後者才是 monitoring rebuild 的 canonical manifest 來源。
- `config/manifests/experiment/` 指向 `autoscale-source-split/02-experiment-layer/` 的 canonical experiment manifests。
- `config/manifests/bundle/` 指向 `k3s-migration-bundle-sanitized/` 的 migration/reference snapshot；它不是 source tree 的雙向同步目標。
- 修改設定時應先沿 symlink 找到實體檔案並在其 canonical 位置修改。不要把 `config/` 入口複製成新的維護來源。

## 使用方式

最簡單的理解方式：

- 想找**公開可版控設定**：先看 `config/`
- 想找**私有 live 設定**：看 `config/private-runtime/` 或 `pre6g-private/`
- 想找**常用 YAML**：看 `config/manifests/`

如果之後還有新的設定類型，也建議延續這種分類方式往下加，不要再把入口分散到新的位置。
