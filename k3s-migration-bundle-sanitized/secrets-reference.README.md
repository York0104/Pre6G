# Secrets Reference Checklist

This sanitized bundle intentionally excludes private keys, kubeconfig, and host-specific credentials.

Use this checklist after cloning `k3s-migration-bundle-sanitized` on the target machine.

## 1. Required Secret / Local Access Files

| Purpose | Expected path on target host | Source on old host | Required? |
| --- | --- | --- | --- |
| RFSoC SSH private key | `~/.ssh/id_ed25519_rfsoc` | `/home/iccl-cluster-z2/.ssh/id_ed25519_rfsoc` | Yes, if RFSoC PL/XRT SSH status is used |
| RFSoC SSH public key | `~/.ssh/id_ed25519_rfsoc.pub` | `/home/iccl-cluster-z2/.ssh/id_ed25519_rfsoc.pub` | Optional but useful |
| OpenWrt AP SSH private key | `~/.ssh/openwrt_ap_ed25519` | `/home/iccl-cluster-z2/.ssh/openwrt_ap_ed25519` | Yes, if AP SSH gateway is used |
| OpenWrt AP SSH public key | `~/.ssh/openwrt_ap_ed25519.pub` | `/home/iccl-cluster-z2/.ssh/openwrt_ap_ed25519.pub` | Optional but useful |
| SSH config aliases | `~/.ssh/config` | `/home/iccl-cluster-z2/.ssh/config` | Recommended |
| kubeconfig | `~/.kube/config` | old `/home/iccl-cluster-z2/.kube/config` only as reference | Yes, but regenerate for the new k3s cluster |
| Helm repo config | `~/.config/helm/repositories.yaml` | `/home/iccl-cluster-z2/.config/helm/repositories.yaml` | Optional; can be recreated with `helm repo add` |

## 2. Recommended Permissions

Run on the target host after placing SSH keys:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/id_ed25519_rfsoc ~/.ssh/openwrt_ap_ed25519
chmod 644 ~/.ssh/id_ed25519_rfsoc.pub ~/.ssh/openwrt_ap_ed25519.pub
chmod 600 ~/.ssh/config
chmod 600 ~/.kube/config
```

## 3. kubeconfig Warning

Do not directly reuse the old kubeconfig unless it was intentionally generated for the new cluster.

The old cluster API server was:

```text
<K3S_SERVER_URL>:6443
```

For a new k3s cluster, generate or copy the new kubeconfig from the new control-plane node, then update:

- API server address
- certificate authority data
- client certificate/key or token
- context name

Verify:

```bash
kubectl get nodes -o wide
kubectl get ns
```

## 4. RFSoC Access

Current RFSoC references:

```text
node name: rfsoc4x2-pynq
lab LAN:   192.168.100.217
Tailscale: 100.91.37.32
metrics:   :9100
```

Relevant config files in this bundle:

- `rfsoc/collector_nodes.json`
- `rfsoc/vm_agg_rfsoc.py`
- `monitoring/scrape.yml`
- `monitoring/vmagent-config-with-rfsoc4x2.yaml`
- `monitoring/vmagent-config-before-rfsoc4x2-lab.yaml`

Verify SSH:

```bash
ssh -i ~/.ssh/id_ed25519_rfsoc rfsoc4x2-pynq hostname
```

Verify node-exporter from the monitoring side:

```bash
curl http://192.168.100.217:9100/metrics | head
curl http://100.91.37.32:9100/metrics | head
```

Use only the route that is valid in the new cluster network.

## 5. OpenWrt AP Access

Current AP references:

```text
AP name: openwrt_ap
AP iface: phy0-ap0
SNMP target: 192.168.1.1
SNMP community: public
SNMP interval: 10s
```

Relevant config files in this bundle:

- `netdata-ap/netdata-snmp-openwrt.current.yaml`
- `netdata-ap/ap_gateway/ap_gateway.py`
- `netdata-ap/ap_gateway/ap_snmp_gateway.py`
- `netdata-ap/vm_agg_ap_gateway.py`

Verify SNMP:

```bash
snmpget -v2c -c public 192.168.1.1 1.3.6.1.2.1.1.1.0
```

Verify SSH if using AP SSH gateway:

```bash
ssh -i ~/.ssh/openwrt_ap_ed25519 root@192.168.1.1 'iw dev phy0-ap0 station dump | head'
```

If the AP IP, interface, or SNMP community changes, update:

- `netdata-ap/netdata-snmp-openwrt.current.yaml`
- AP gateway environment variables: `OPENWRT`, `AP_IFACE`, `SNMP_COMMUNITY`

## 6. API Token

The actual AutoScale API token is not stored in this bundle.

If token authentication is enabled, create a local env file in the AutoScale repo:

```bash
cat > /home/icclz2/Pre6G/systemd/autoscale-api.env <<'EOF'
AUTOSCALE_API_TOKEN=replace-with-a-real-long-random-token
EOF
chmod 600 /home/icclz2/Pre6G/systemd/autoscale-api.env
```

The tracked example lives in AutoScale:

```text
systemd/autoscale-api.env.example
```

## 7. YOLO Image

The current workload references a local image:

```text
local/yolo26n:0.5
imagePullPolicy: Never
```

This is not a secret, but it is a local runtime dependency. On the new GPU worker, either:

- rebuild/import the same image tag, or
- push the image to a private registry and update the workload YAML.

Relevant files:

- `thermal-yolo/yolo26_workload/Dockerfile`
- `thermal-yolo/yolo26_workload/app.py`
- `thermal-yolo/intent-lab-yolo-workloads.current.yaml`
- `thermal-yolo/experiments_yolo/saturation_multi_pod/yolo26_task3_saturation.yaml`

## 8. Worker-Side Thermal Control

The fan/thermal controller is not part of this bundle and was located on the worker:

```text
/home/REPLACE_GPU_USER/gpu-tempctl-lab/fan_control_lab/gpu_cycle_runner.py
```

On the new worker, restore or rebuild that project before running thermal experiments.

Verify:

```bash
ssh <new-worker> 'test -f /home/REPLACE_GPU_USER/gpu-tempctl-lab/fan_control_lab/gpu_cycle_runner.py && echo OK'
ssh <new-worker> 'nvidia-smi'
```

## 9. Final Validation

After restoring secrets and applying manifests, verify:

```bash
kubectl get pods -A
kubectl -n monitoring get cm vmagent-victoria-metrics-agent-config -o yaml
kubectl -n gpu-monitoring get cm exporter-metrics-config-map -o yaml
kubectl -n nvidia-device-plugin get cm gpu-sharing-config -o yaml
kubectl -n netdata get cm netdata-snmp-openwrt -o yaml
```

Then query metrics:

```bash
curl 'http://<victoria-metrics-url>/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP'
curl 'http://<victoria-metrics-url>/api/v1/query?query=node_cpu_seconds_total'
```

