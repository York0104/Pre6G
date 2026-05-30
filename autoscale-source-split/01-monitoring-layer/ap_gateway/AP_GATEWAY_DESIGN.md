# AP Gateway Metrics Design

## Overview

這份文件是 AP gateway 監控鏈路的單一設計基準，整理目前 repo 內

- `autoscale-source-split/01-monitoring-layer/ap_gateway/`
- `autoscale-source-split/01-monitoring-layer/vm_agg_ap_gateway.py`

的設計，說明：

- 三支程式各自負責什麼
- 三者之間的資料依賴關係
- 平常如何啟動、檢查、查詢
- `vm_agg_ap_gateway.py` 輸出的欄位意義
- 後續如果要擴充成多個 gateway 或包成 Pod，現有設計的基礎是什麼

相關程式：

- `ap_gateway/ap_gateway.py`
- `ap_gateway/ap_snmp_gateway.py`
- `vm_agg_ap_gateway.py`

## Architecture

目前整體資料流如下：

1. `ap_gateway.py`
   透過 SSH 連到 OpenWrt AP，執行 `iw dev <iface> station dump`
   收集無線 station 原始資訊
   轉成 Prometheus metrics
   push 到 VictoriaMetrics

2. `ap_snmp_gateway.py`
   透過 SNMP 向 OpenWrt AP 查詢 CPU、memory、swap、load、介面統計
   轉成 Prometheus metrics
   push 到 VictoriaMetrics

3. `vm_agg_ap_gateway.py`
   不直接連 AP
   而是查詢 VictoriaMetrics 中已存在的 `ap_wifi_*` 與 `ap_node_*` metrics
   將資料整理成一份 access node semantic JSON

也就是說：

- `ap_gateway.py` 是無線資料 producer
- `ap_snmp_gateway.py` 是硬體資料 producer
- `vm_agg_ap_gateway.py` 是聚合查詢器

## Dependency Model

三支程式之間沒有 Python `import` 依賴，但有資料管線依賴。

### Code-level dependency

沒有直接依賴：

- `ap_gateway.py` 不會 import 另外兩支
- `ap_snmp_gateway.py` 不會 import 另外兩支
- `vm_agg_ap_gateway.py` 也不會 import 前兩支

### Data-level dependency

有間接依賴：

- `vm_agg_ap_gateway.py` 依賴 `ap_gateway.py` 先將 `ap_wifi_*` metrics 寫入 VictoriaMetrics
- `vm_agg_ap_gateway.py` 依賴 `ap_snmp_gateway.py` 先將 `ap_node_*` metrics 寫入 VictoriaMetrics

如果前兩支沒跑，或 metrics 沒有成功送到 VM，`vm_agg_ap_gateway.py` 就無法輸出完整結果。

## Program Roles

### `ap_gateway.py`

功能：

- 透過 SSH 到 AP 執行 `iw dev <iface> station dump`
- 解析 station 清單
- 將 station MAC 做 hash 匿名化
- 產生 `ap_wifi_*` Prometheus metrics
- push 到 VictoriaMetrics import endpoint

主要環境變數：

- `OPENWRT`
- `AP_IFACE`
- `AP_NAME`
- `SSH_KEY`
- `INTERVAL`
- `VM_URL`
- `MAC_SALT`

輸出的主要 metrics：

- `ap_wifi_station_count`
- `ap_wifi_station_inactive_ms`
- `ap_wifi_station_rx_bytes`
- `ap_wifi_station_tx_bytes`
- `ap_wifi_station_rx_packets`
- `ap_wifi_station_tx_packets`
- `ap_wifi_station_tx_retries`
- `ap_wifi_station_tx_failed`
- `ap_wifi_station_signal_dbm`
- `ap_wifi_station_signal_avg_dbm`
- `ap_wifi_station_tx_bitrate_mbps`
- `ap_wifi_station_rx_bitrate_mbps`
- `ap_wifi_station_connected_seconds`

### `ap_snmp_gateway.py`

功能：

- 透過 SNMP 查詢 AP 主機與介面狀態
- 將 SNMP OID 對應到 Prometheus metrics
- push 到 VictoriaMetrics import endpoint

主要環境變數：

- `OPENWRT`
- `AP_NAME`
- `AP_IFACE`
- `SNMP_COMMUNITY`
- `SNMP_IFINDEX`
- `INTERVAL`
- `VM_URL`

輸出的主要 metrics：

- `ap_node_load1`
- `ap_node_load5`
- `ap_node_load15`
- `ap_node_cpu_usage_percent`
- `ap_node_cpu_idle_percent`
- `ap_node_cpu_user_percent`
- `ap_node_cpu_system_percent`
- `ap_node_cpu_num_cores`
- `ap_node_memory_total_bytes`
- `ap_node_memory_available_bytes`
- `ap_node_memory_used_bytes`
- `ap_node_memory_usage_percent`
- `ap_node_memory_buffer_bytes`
- `ap_node_memory_cached_bytes`
- `ap_node_swap_total_bytes`
- `ap_node_swap_available_bytes`
- `ap_node_iface_rx_bytes_total`
- `ap_node_iface_tx_bytes_total`
- `ap_node_iface_rx_errors_total`
- `ap_node_iface_tx_errors_total`
- `ap_node_iface_admin_status`
- `ap_node_iface_oper_status`

### `vm_agg_ap_gateway.py`

功能：

- 從 VictoriaMetrics 查詢 AP 無線與硬體資料
- 輸出一份 JSON 格式的 access node semantic profile

主要輸出區塊：

- `meta`
- `access_node_semantic.wireless_access`
- `access_node_semantic.stations`
- `access_node_semantic.device_resource`
- `access_node_semantic.interface_traffic`

## Runtime Model

### `ap_gateway.py` 與 `ap_snmp_gateway.py`

這兩支是長駐收集器。

原因：

- 兩支程式的 `main()` 都有 `while True`
- 每隔 `INTERVAL` 秒收一次
- 收到後立即 push 到 VictoriaMetrics

因此它們適合：

- 在背景持續執行
- 以 host-side `systemd service` 正式常駐
- `Kubernetes Pod` 僅保留作為未來特殊部署選項

### `vm_agg_ap_gateway.py`

這支不是長駐收集器，而是查詢器。

功能模式：

- 執行一次
- 查一次 VictoriaMetrics
- 輸出當下 JSON
- 然後結束

所以實務上通常是：

1. 讓前兩支常駐收集
2. 需要看 AP 當下狀態時，再手動執行 `vm_agg_ap_gateway.py`

## Current Stable Configuration

目前穩定可用的基準設定如下：

- `OPENWRT=192.168.1.1`
- `AP_NAME=openwrt_ap`
- `AP_IFACE=phy0-ap0`
- `SNMP_IFINDEX=3`
- VictoriaMetrics query base URL: `http://<CONTROL_PLANE_IP>:31888`
- VictoriaMetrics import endpoint: `http://<CONTROL_PLANE_IP>:31888/api/v1/import/prometheus`

這裡要特別注意兩種 `VM_URL` 的語意不同：

- 對 `ap_gateway.py` 與 `ap_snmp_gateway.py` 而言，`VM_URL` 是 import endpoint
- 對 `vm_agg_ap_gateway.py` 而言，`VM_URL` 是 query base URL

先前 AP metrics 查不到的根因，就是 producer 雖然仍在背景執行，但預設 import endpoint 還指向舊的 `127.0.0.1:8428`。這會導致採集成功、匯入失敗，最後 aggregator 查不到資料。現在已統一改成 NodePort 架構。

## Recommended Service Layout

目前正式重建路徑建議直接使用 repo 內的 `systemd` 範本：

- `/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-gateway.service`
- `/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-gateway.env.example`
- `/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-snmp-gateway.service`
- `/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-snmp-gateway.env.example`

最小安裝步驟：

```bash
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-gateway.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-gateway.env
cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-snmp-gateway.env.example \
   /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-snmp-gateway.env
sudo cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-gateway.service /etc/systemd/system/
sudo cp /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/systemd/ap-snmp-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ap-gateway.service ap-snmp-gateway.service
```

狀態檢查：

```bash
systemctl status ap-gateway.service --no-pager
systemctl status ap-snmp-gateway.service --no-pager
journalctl -u ap-gateway.service -n 50 --no-pager
journalctl -u ap-snmp-gateway.service -n 50 --no-pager
```

`tmux` 僅保留作為手動除錯方式，不再是建議的正式常駐方案。

## Typical Commands

### 啟動無線原始資料收集

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/ap_gateway
VM_URL=http://<CONTROL_PLANE_IP>:31888/api/v1/import/prometheus \
OPENWRT=192.168.1.1 \
AP_NAME=openwrt_ap \
AP_IFACE=phy0-ap0 \
python3 ap_gateway.py
```

### 啟動硬體原始資料收集

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/ap_gateway
VM_URL=http://<CONTROL_PLANE_IP>:31888/api/v1/import/prometheus \
OPENWRT=192.168.1.1 \
AP_NAME=openwrt_ap \
AP_IFACE=phy0-ap0 \
SNMP_COMMUNITY=public \
SNMP_IFINDEX=3 \
python3 ap_snmp_gateway.py
```

### 查詢當下整合後 AP 狀態

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer
VM_URL=http://<CONTROL_PLANE_IP>:31888 \
AP_NAME=openwrt_ap \
AP_IFACE=phy0-ap0 \
OPENWRT=192.168.1.1 \
python3 vm_agg_ap_gateway.py
```

## Health Check Commands

### 檢查兩個 collector 是否還在跑

```bash
ps -ef | grep -E 'ap_gateway.py|ap_snmp_gateway.py' | grep -v grep
```

或：

```bash
pgrep -af 'ap_gateway.py|ap_snmp_gateway.py'
```

### 確認 VictoriaMetrics 有收到無線資料

```bash
curl -s 'http://<CONTROL_PLANE_IP>:31888/api/v1/query?query=ap_wifi_station_count' | jq '.data.result'
```

### 確認 VictoriaMetrics 有收到硬體資料

```bash
curl -s 'http://<CONTROL_PLANE_IP>:31888/api/v1/query?query=ap_node_cpu_usage_percent' | jq '.data.result'
```

### 一次檢查 collector 與 VM

```bash
pgrep -af 'ap_gateway.py|ap_snmp_gateway.py' && echo '---' && \
curl -s 'http://<CONTROL_PLANE_IP>:31888/api/v1/query?query=ap_wifi_station_count' | jq '.data.result' && \
curl -s 'http://<CONTROL_PLANE_IP>:31888/api/v1/query?query=ap_node_cpu_usage_percent' | jq '.data.result'
```

## Current Rebuild Status (2026-05-29)

目前 `iccl-cluster-z2` host 端已可直接到達 OpenWrt AP，且 SSH 與 SNMP 都已可用：

```bash
curl -I http://192.168.1.1
ssh -i ~/.ssh/openwrt_ap_ed25519 root@192.168.1.1 "ip addr show br-lan"
snmpwalk -v2c -c public 192.168.1.1 1.3.6.1.2.1.1
```

目前重建進度如下：

- `ap_gateway.py` 已打通，並可在 host 上常駐執行
- `ap_snmp_gateway.py` 已打通，並可在 host 上常駐執行
- `VictoriaMetrics` 已可查到：
  - `ap_wifi_station_count{ap="openwrt_ap"}`
  - `ap_node_cpu_usage_percent{ap="openwrt_ap"}`
- `vm_agg_ap_gateway.py` 已可完整輸出 `collector_status = ok`，且 `device_resource` / `interface_traffic` / `node_pressure` 欄位已有值

因此目前 AP gateway 重建主線已打通；後續建議是：

1. 將兩支 collector 以 host-side `systemd service` 常駐
2. 用 `systemctl status` / `journalctl` 取代 `tmux` 作為主要維運方式
3. 若 OpenWrt 的 SNMP community 或介面 index 變更，需同步更新 collector env 或執行參數

補充：目前 cluster 內 Pod 對 `192.168.1.1` 僅驗到 `UDP/161` 可達，但 `TCP/22` / `TCP/80` timeout，因此不建議先把 AP collectors 改成 Pod 內執行。

## Current Output Design

`vm_agg_ap_gateway.py` 輸出格式目前為：

```json
{
  "schema": "intentcontinuum.access_node.v1",
  "collector_status": "ok",
  "meta": {...},
  "access_node_semantic": {
    "source": "ap_gateway+snmp_gateway+victoriametrics",
    "wireless_access": {...},
    "stations": [...],
    "device_resource": {...},
    "interface_traffic": {...}
  }
}
```

## Field Introduction

### `meta`

用途：

- 說明這份 JSON 是誰觀察、觀察哪個 AP、哪個介面、從哪個 VM 查

欄位：

- `timestamp`: 查詢當下 UNIX timestamp
- `observer`: 執行此查詢腳本的主機名稱
- `target_node`: AP 邏輯名稱，對應 `AP_NAME`
- `target_ip`: AP IP，對應 `OPENWRT`
- `iface`: 無線介面，對應 `AP_IFACE`
- `role`: 固定描述目前這份 profile 的角色
- `vm_url`: 查詢用的 VictoriaMetrics URL
- `rate_window`: 速率查詢使用的 PromQL rate window

### `wireless_access`

用途：

- 描述整台 AP 在無線接入層的聚合狀態

欄位：

- `station_count`
  目前連線 station 數量
- `tx_bits_per_s`
  AP 對所有 station 的總傳送速率
- `rx_bits_per_s`
  AP 對所有 station 的總接收速率
- `avg_tx_bitrate_mbps`
  station 平均 Tx bitrate
- `avg_rx_bitrate_mbps`
  station 平均 Rx bitrate
- `tx_failed_per_s`
  `ap_wifi_station_tx_failed` 經 `rate(...)` 轉換後的每秒失敗率
- `avg_inactive_ms`
  station 平均 inactive time
- `max_inactive_ms`
  station 最大 inactive time
- `avg_connected_seconds`
  station 平均連線時間

### `stations`

用途：

- 保留每一個 station 的個別狀態

欄位：

- `station`
  station 匿名化後 ID
- `inactive_ms`
  該 station 最近 inactive 時間
- `connected_seconds`
  該 station 連線秒數
- `tx_bitrate_mbps`
  station Tx bitrate
- `rx_bitrate_mbps`
  station Rx bitrate
- `tx_bits_per_s`
  station Tx 速率
- `rx_bits_per_s`
  station Rx 速率
- `tx_failed_total`
  累積 Tx failed 次數

### `device_resource`

用途：

- 描述 AP 本機硬體與系統資源狀態

欄位：

- `source`
  目前為 `snmp_gateway+victoriametrics`
- `cpu_usage_ratio`
  CPU 已使用比例，範圍 `0~1`
- `cpu_idle_ratio`
  CPU 閒置比例，範圍 `0~1`
- `cpu_user_ratio`
  CPU user space 比例，範圍 `0~1`
- `cpu_system_ratio`
  CPU system/kernel 比例，範圍 `0~1`
- `cpu_num_cores`
  CPU 核心數
- `memory_total_bytes`
  記憶體總量
- `memory_available_bytes`
  可用記憶體
- `memory_used_bytes`
  已使用記憶體
- `memory_buffer_bytes`
  memory buffer 大小
- `memory_cached_bytes`
  memory cache 大小
- `memory_usage_ratio`
  記憶體使用比例，範圍 `0~1`
- `swap_total_bytes`
  swap 總量
- `swap_available_bytes`
  swap 可用量
- `load1`
  最近 1 分鐘 load average
- `load5`
  最近 5 分鐘 load average
- `load15`
  最近 15 分鐘 load average

### `interface_traffic`

用途：

- 描述指定介面 `AP_IFACE` 的流量與基本健康度

欄位：

- `source`
  目前為 `snmp_gateway+victoriametrics`
- `iface`
  介面名稱
- `rx_bits_per_s`
  接收速率，來自 `ap_node_iface_rx_bytes_total` 經 `rate(...) * 8`
- `tx_bits_per_s`
  傳送速率，來自 `ap_node_iface_tx_bytes_total` 經 `rate(...) * 8`
- `rx_errors_per_s`
  接收錯誤率
- `tx_errors_per_s`
  傳送錯誤率
- `admin_status`
  介面管理狀態，通常 `1` 表示 administratively up
- `oper_status`
  介面操作狀態，通常 `1` 表示 operationally up

## Why These Fields Are Kept

目前保留的欄位以兩類為主：

1. 直接量測值
2. 明確數學轉換值

例如：

- `rate(counter[window])`
- `rate(counter[window]) * 8`
- 百分比除以 `100` 轉成 `0~1` ratio
- KB 轉 bytes

目前已移除的，是較偏 heuristic 或假設型的 decision 欄位，例如：

- `active_station_count`
- `station_ratio`
- `access_load_score`
- `wireless_quality_score`
- `decision_hint`

因此目前這份 `vm_agg_ap_gateway.py` 的設計較偏：

- observation-oriented
- metric-preserving
- low-assumption semantic profile

## Current Known Good State

以下內容代表這條 AP gateway 鏈路在舊環境中曾成功驗證過的 known-good 行為；目前 `iccl-cluster-z2` 也已重新打通，但這一段仍應視為 historical reference：

- `ap_gateway.py` 與 `ap_snmp_gateway.py` 都有在背景執行
- VictoriaMetrics 可查到代表性 AP metrics：
  - `ap_wifi_station_count{ap="openwrt_ap",iface="phy0-ap0",target="192.168.1.1"}`
  - `ap_node_cpu_usage_percent{ap="openwrt_ap",target="192.168.1.1"}`
- `vm_agg_ap_gateway.py` 可正常輸出 `collector_status: "ok"` 的 semantic JSON

當時驗到的代表性輸出如下：

- `station_count = 0`
- `stations = []`
- `cpu_usage_ratio = 0.01`
- `cpu_idle_ratio = 0.99`
- `cpu_num_cores = 4`
- `memory_usage_ratio ~= 0.02096`
- `admin_status = 1`
- `oper_status = 1`

這表示舊環境中曾成立：

- 無線 collector 正常
- SNMP collector 正常
- VictoriaMetrics import 與 query 路徑正常
- `vm_agg_ap_gateway.py` 可以正常作為前端查詢器使用

目前 `iccl-cluster-z2` 的重建狀態請以前面的 `Current Rebuild Status (2026-05-29)` 為準；目前已完成 host-side 重建驗證，且 `ap_wifi_station_count` / `ap_node_cpu_usage_percent` 均已可在 VM 中查到。

另外要注意，`station_count = 0` 與 `stations = []` 不一定代表壞掉；如果當下沒有 Wi-Fi client 連線，這就是合理結果。

## Multi-Gateway Extension Direction

如果之後會有多個 gateway，建議沿用目前這個模式：

- 一台 gateway 對應一組 collector
- 每組 collector 帶不同環境變數
- 以不同 `AP_NAME` / `OPENWRT` / `AP_IFACE` 區分

推薦命名：

- `AP_NAME=openwrt_ap_gw1`
- `AP_NAME=openwrt_ap_gw2`

查詢單台 gateway 時，執行：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer
VM_URL=http://<CONTROL_PLANE_IP>:31888 \
AP_NAME=openwrt_ap_gw1 \
AP_IFACE=phy0-ap0 \
OPENWRT=192.168.1.1 \
python3 vm_agg_ap_gateway.py
```

## Future Pod Packaging Direction

目前這個設計已經適合後續包成 Pod：

- `ap_gateway.py` 可作為長駐 collector container
- `ap_snmp_gateway.py` 可作為長駐 collector container
- `vm_agg_ap_gateway.py` 可作為查詢工具，保留在操作節點執行，或之後做成 on-demand job / API

比較建議的做法是：

- 一台 gateway 對應一個 Deployment
- Deployment 內放兩個 container
  - `ap_gateway.py`
  - `ap_snmp_gateway.py`

前提：

- Pod 所在節點可連到 AP 的 SSH 與 SNMP
- Pod 可連到 VictoriaMetrics
- SSH key 可由 Secret 掛載
- container image 內有 `ssh` 與 `snmpget`

## Summary

這套 AP gateway 設計目前已具備：

- 無線與硬體雙來源收集
- 透過 VictoriaMetrics 做統一儲存與查詢
- 一次性查詢輸出結構化 JSON
- 可持續背景執行
- 可擴充至多 gateway
- 可進一步包裝成 Pod / Deployment

目前最推薦的操作模式是：

1. 常駐執行 `ap_gateway.py`
2. 常駐執行 `ap_snmp_gateway.py`
3. 需要看當下 AP 整合狀態時，再執行 `vm_agg_ap_gateway.py`
