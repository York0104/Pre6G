# RFSoC

本資料夾保存 RFSoC aggregator 與 node inventory 參考。

| 檔案 | 說明 |
| --- | --- |
| `collector_nodes.json` | 外部 RFSoC node entry 與環境變數提示。 |
| `vm_agg_rfsoc.py` | RFSoC-specific aggregator。 |
| `vm-aggregators-reference.md` | aggregator schema 與欄位參考。 |

vmagent RFSoC scrape config 位於 `../monitoring/`。目前 targets：

```text
Lab LAN:   192.168.100.217:9100
Tailscale: 100.91.37.32:9100
```

RFSoC SSH key 不在 sanitized copy；請透過 private handoff 恢復為 `~/.ssh/id_ed25519_rfsoc` 或設定 `PL_STATUS_SSH_KEY`。
