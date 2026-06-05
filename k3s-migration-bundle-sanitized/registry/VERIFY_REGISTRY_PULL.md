# Verify Harbor Pull

## 1. 檢查 registries.yaml

```bash
cat /etc/rancher/k3s/registries.yaml
```

確認：

- endpoint 是否寫對
- 若使用 HTTPS，endpoint 是否明確包含 `https://`
- 若使用自簽 CA，`ca_file` 是否存在
- auth 是否對應正確的 Harbor robot account

目前實際建議值：

```yaml
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
```

## 2. 重啟 k3s

```bash
sudo systemctl restart k3s
sudo systemctl restart k3s-agent
```

## 3. 直接測試 pull

```bash
sudo crictl pull harbor.iccl.local:8088/pre6g/yolo26n:0.1
```

或：

```bash
sudo k3s ctr images pull \
  --user 'robot$pre6g+pre6g-pull:<HARBOR_ROBOT_TOKEN>' \
  harbor.iccl.local:8088/pre6g/yolo26n:0.1
```

## 4. 常見錯誤

- `x509: certificate signed by unknown authority`
  - CA 未放到 node，或 `ca_file` 路徑不正確。
- `401 Unauthorized`
  - Harbor 帳號 / token 不對，或 robot account 缺 pull 權限。
- `no basic auth credentials`
  - `crictl pull` 在本環境下可能仍不會自動吃進 Harbor auth；請先確認 `config.toml` 已出現 auth，必要時使用 `sudo k3s ctr images pull --user ...` 先完成預載。
- `dial tcp` / `no route to host`
  - node 無法到 Harbor，請先檢查 LAN / DNS / firewall。
- `http: server gave HTTP response to HTTPS client`
  - 你仍在使用舊的 HTTP Harbor；本輪正式重建已改為 `HTTPS:8088`。

## 5. 觀察 log

```bash
journalctl -u k3s -f
journalctl -u k3s-agent -f
```

必要時再看：

```bash
tail -f /var/lib/rancher/k3s/agent/containerd/containerd.log
```

## 6. 2026-06-04 實測結論

- `HTTPS + 自簽 Harbor CA + robot pull account` 已可讓 worker 成功使用 Harbor image
- 在 `icclz1` 上，以下指令已實測成功：

```bash
sudo k3s ctr images pull \
  --user 'robot$pre6g+pre6g-pull:<HARBOR_ROBOT_TOKEN>' \
  harbor.iccl.local:8088/pre6g/yolo26n:0.1
```

- 配合 `imagePullPolicy: IfNotPresent`，刪除舊 pod 後，registry 版 `yolo26n-focus/bg-1/bg-2` 已全部成功回到 `Running`
