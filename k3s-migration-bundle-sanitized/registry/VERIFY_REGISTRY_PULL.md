# Verify Harbor Pull

## 1. 檢查 registries.yaml

```bash
cat /etc/rancher/k3s/registries.yaml
```

確認：

- endpoint 是否寫對
- 若使用純 HTTP，endpoint 是否明確包含 `http://`
- 若使用自簽 CA，`ca_file` 是否存在
- auth 是否對應正確的 Harbor robot account

## 2. 重啟 k3s

```bash
sudo systemctl restart k3s
sudo systemctl restart k3s-agent
```

## 3. 直接測試 pull

```bash
sudo crictl pull harbor.iccl.local/pre6g/yolo26n:0.1
```

或：

```bash
sudo k3s ctr images pull harbor.iccl.local/pre6g/yolo26n:0.1
```

## 4. 常見錯誤

- `x509: certificate signed by unknown authority`
  - CA 未放到 node，或 `ca_file` 路徑不正確。
- `401 Unauthorized`
  - Harbor 帳號 / token 不對，或 robot account 缺 pull 權限。
- `dial tcp` / `no route to host`
  - node 無法到 Harbor，請先檢查 LAN / DNS / firewall。
- `http: server gave HTTP response to HTTPS client`
  - 你在用 HTTP Harbor，但 `registries.yaml` endpoint 沒寫 `http://`。

## 5. 觀察 log

```bash
journalctl -u k3s -f
journalctl -u k3s-agent -f
```

必要時再看：

```bash
tail -f /var/lib/rancher/k3s/agent/containerd/containerd.log
```
