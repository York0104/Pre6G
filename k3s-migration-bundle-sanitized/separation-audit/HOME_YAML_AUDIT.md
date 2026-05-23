# Home YAML / CSV Audit

This checks root-level files from `/home/iccls2` and whether they are included in the handoff package.

## Included And Useful

| Source file | Handoff location | Note |
| --- | --- | --- |
| `calico-installation-tailscale0.yaml` | `cluster-access/calico-installation-tailscale0.yaml` | Calico/Tailscale interface reference |
| `custom-resources.yaml` | `cluster-access/custom-resources.yaml` | Calico operator Installation/APIServer CRs |
| `dcgm-exporter.yaml` | `gpu/dcgm-exporter.yaml` | DCGM exporter reference |
| `dcgm-values.yaml` | `gpu/dcgm-values.yaml` | DCGM Helm values/reference |
| `exporter-metrics-config-map.new.yaml` | `gpu/exporter-metrics-config-map.new.yaml` | DCGM metrics ConfigMap candidate |
| `gpu-sharing-icclz1.yaml` | `nvidia-device-plugin/gpu-sharing-icclz1.yaml` | GPU sharing config reference |
| `nvdp-values-before.yaml` | `nvidia-device-plugin/nvdp-values-before.yaml` | NVIDIA device plugin previous values reference |
| `scrape.yml` | `monitoring/scrape.yml` | vmagent scrape reference |
| `vmagent-config-auto-discovery.yaml` | `monitoring/vmagent-config-auto-discovery.yaml` | vmagent auto-discovery reference |
| `vmagent-config-before-rfsoc4x2-lab.yaml` | `monitoring/vmagent-config-before-rfsoc4x2-lab.yaml` | pre-RFSoC/lab RFSoC reference |
| `vmagent-config-gpu-1s.yaml` | `monitoring/vmagent-config-gpu-1s.yaml` | 1-second GPU scrape reference |
| `vmagent-config-with-rfsoc4x2.yaml` | `monitoring/vmagent-config-with-rfsoc4x2.yaml` | RFSoC scrape reference |

## Included As Backup / Smoke Reference

| Source file | Handoff location | Note |
| --- | --- | --- |
| `dcgm-exporter.backup.yaml` | `gpu/dcgm-exporter.backup.yaml` | backup/export reference, not primary |
| `exporter-metrics-config-map.backup.yaml` | `gpu/exporter-metrics-config-map.backup.yaml` | backup/export reference, not primary |
| `test-gpu-shared.yaml` | `nvidia-device-plugin/test-gpu-shared.yaml` | GPU sharing smoke test |
| `test-gpu-shared-5.yaml` | `nvidia-device-plugin/test-gpu-shared-5.yaml` | GPU sharing smoke test |

## Covered By Current Live Exports Or Newer Files

| Source file | Replacement / coverage | Note |
| --- | --- | --- |
| `metrics.csv` | `gpu/exporter-metrics-config-map.current.yaml` and `gpu/exporter-metrics-config-map.new.yaml` | DCGM metric whitelist is embedded in ConfigMap YAML |
| `vmagent-victoria-metrics-agent-config.yaml` | `monitoring/live-exports/vmagent-config.current.yaml` plus curated vmagent configs | older root-level ConfigMap export |
| `vmagent-victoria-metrics-agent-config.backup.yaml` | `monitoring/live-exports/vmagent-config.current.yaml` plus curated vmagent configs | older backup export |
| `vmagent-config-before-rfsoc-labip.yaml` | `monitoring/vmagent-config-with-rfsoc4x2.yaml` | same content hash as the included RFSoC config |

## Not Included Because They Are Test / Old / Runtime State

| Source file | Reason |
| --- | --- |
| `test-worker-icclz1.yaml` | nginx node-placement smoke test, not required for migration |
| `test-worker-z590.yaml` | nginx node-placement smoke test for older/other worker |
| `vm-aggregator-stuck-pod.yaml` | `kubectl get pod` dump of a stuck runtime pod, not reusable desired state |
| `yolo26n-gpu-shared-icclz1.yaml` | older YOLO shared-GPU manifest using `local/yolo26n:0.1`; current handoff uses newer YOLO26 manifests/workload export |

## Other K8s Rebuild References Added

These were found under `AutoScale/rebuild_bundle_temp/exports/` and are useful for k3s rebuild verification:

```text
monitoring/live-exports/helm-manifests/
monitoring/live-exports/helm-status/
monitoring/live-exports/image-digests/
cluster-access/live-exports/
```

Notes:

- `helm-manifests/` are rendered Helm output. Use them for comparison/debugging, not as the first-choice install source.
- `helm-values-*.current.yaml` and the rebuild README remain the preferred source for reinstalling Helm releases.
- `cluster-access/live-exports/` captures node names, node versions, and kubectl client version from the source cluster.
- `exp_runs/*/k8s/` was not copied because it contains historical experiment snapshots rather than reusable desired state.
- `/home/iccls2/k8s-arm64/` was not copied because it contains large Kubernetes binaries, not configuration.
