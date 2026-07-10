# Node Protection Config Notes

These files are example K3s / kubelet configuration fragments.

They are not applied with `kubectl apply -k`.

Current prepared example:

- `k3s-agent-eviction-hard.example.yaml`

Recommended workflow:

1. back up `/etc/rancher/k3s/config.yaml`
2. merge the `kubelet-arg` entry into the live K3s agent config
3. restart `k3s-agent`
4. verify `Node Ready=True` before any stress validation
