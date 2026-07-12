# k3s Migration Bundle

本資料夾用於在另一個 k3s cluster 重建監控、AP/RFSoC observability 與 thermal YOLO 實驗。此版本已排除 private secrets。

> [!IMPORTANT]
> 此目錄是 migration/reference snapshot，不是 `autoscale-source-split/` 或 `monitoring-rebuild/` 的雙向同步副本。相同檔案可作為可攜交付內容保留；分歧檔案應先與 canonical source 比對後再使用。此 snapshot 的原始生成時間與 source revision 為 `UNVERIFIED`，不可僅以檔案時間判定新舊。

Canonical boundary:

- monitoring rebuild manifests: `../monitoring-rebuild/`
- source-level code, API/dashboard, and experiment definitions: `../autoscale-source-split/`
- public/private configuration entry points: `../config/`

## 建議重建順序

1. 建立新 k3s cluster，確認 node name、CNI、Tailscale/LAN routing、NVIDIA driver 與 container runtime。
2. 依 private handoff 恢復 kubeconfig/SSH/Helm repo 等必要私密資訊；不要直接覆蓋新 cluster kubeconfig。
3. 使用 `nvidia-device-plugin/` 安裝 NVIDIA Device Plugin 與 GPU sharing。
4. 使用 `monitoring/` 安裝 VictoriaMetrics、vmagent、node-exporter、kube-state-metrics。
5. 使用 `gpu/` 安裝 DCGM exporter 與自訂 metrics ConfigMap。
6. 使用 `netdata-ap/` 安裝 Netdata、AP SNMP/gateway 相關設定。
7. 使用 `rfsoc/` 與 vmagent RFSoC scrape config 恢復 RFSoC monitoring。
8. 依 `registry/REBUILD_STEPS.md` 配置 Harbor registry，決定使用 Harbor pull 或保留 manual build/import YOLO image。
9. 套用 `thermal-yolo/` workload。
10. 驗證 PromQL targets、DCGM metrics、Netdata/cAdvisor metrics、AP metrics、RFSoC node-exporter metrics，以及 YOLO `/healthz`。

## 目錄說明

| 路徑 | 說明 |
| --- | --- |
| `monitoring/` | vmagent scrape config、Helm values、rendered manifests、status、image digest 與 live export。 |
| `gpu/` | DCGM exporter values、metrics ConfigMap 與 GPU thermal throttling 相關 reference。 |
| `nvidia-device-plugin/` | NVIDIA Device Plugin values、GPU time-slicing/sharing config 與 smoke test manifests。 |
| `netdata-ap/` | Netdata values、NodePort、AP gateway scripts、OpenWrt AP SNMP export。 |
| `rfsoc/` | RFSoC aggregator/config 參考與 RFSoC VM aggregator 文件。 |
| `registry/` | Harbor registry、Kaniko build、k3s `registries.yaml`、implementation progress 與 rebuild SOP。 |
| `thermal-yolo/` | thermal analysis scripts、YOLO k8s app/manifests、目前 `intent-lab` workload export。 |
| `cluster-access/` | Calico/CNI、NodePort、in-cluster aggregator Job、node/version live export。 |
| `separation-audit/` | 監控/實驗分離、AutoScale 檔案分組、舊版/無用候選與 home YAML audit。 |
| `external-worker/` | worker-side 檔案缺口說明，例如 `gpu-tempctl-lab`。 |
| `secrets-reference.README.md` | private secrets 與本機依賴恢復 checklist；sanitized copy 不含 secrets。 |
| `MANIFEST.txt` | bundle 歷史交付快照清單；目前 Git 追蹤內容請以 `git ls-files` 為準。 |

## 重要資訊

| 項目 | 目前值 / 說明 |
| --- | --- |
| YOLO image | 目前正式支援與重建流程統一使用 `local/yolo26n:0.1`；repo 另已新增 Harbor registry 版 manifests 與 `registry/` 樣板。`intent-lab` 的歷史 live export 仍可見 `0.5`，請視為舊快照。 |
| RFSoC targets | Lab LAN `192.168.100.217:9100`；Tailscale `100.91.37.32:9100`。 |
| AP SNMP | target `192.168.1.1`，community `public`，interval `10s`。 |
| GPU sharing | current live ConfigMap 為 `replicas: 100`；舊註解/備份可能仍提到 `4`。 |
| AutoScale source | 實際分層 source 在 `../autoscale-source-split/`。 |

## Registry Rebuild Entry

若你要在新 cluster 直接走 Harbor pull：

1. 先看 `registry/IMPLEMENTATION_PROGRESS.md`
2. 再看 `registry/REBUILD_STEPS.md`
3. 若 pull 失敗，查 `registry/VERIFY_REGISTRY_PULL.md`

## 私密資料

此 sanitized bundle 不包含 `secrets-reference/`。請從：

```text
../current-lab-handoff-private/private-files-to-fill/
```

恢復 kubeconfig、SSH key、API env 與其他 private runtime 值。
