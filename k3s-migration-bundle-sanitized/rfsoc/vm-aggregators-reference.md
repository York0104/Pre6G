# VM Aggregators Reference

本文件整理目前專案中 3 支主要 aggregator 的定位、資料來源、輸出 schema、共同欄位、差異點與已知注意事項。

涵蓋檔案：

- `vm_aggregator.py`
- [`vm_agg_rfsoc.py`](/home/iccls2/AutoScale/vm_agg_rfsoc.py)
- [`vm_agg_ap_gateway.py`](/home/iccls2/AutoScale/vm_agg_ap_gateway.py)

## Summary

| Script | 目標對象 | 主要 schema | 主要資料來源 | 是否 K8s node |
|---|---|---|---|---|
| `vm_aggregator.py` | 一般 K8s node / GPU node | `intentcontinuum.state.v6` | VictoriaMetrics + Netdata + DCGM exporter | 是 |
| `vm_agg_rfsoc.py` | 外部 RFSoC 節點 | `intentcontinuum.state.v6` | Netdata + VictoriaMetrics + PYNQ/XRT SSH status | 否 |
| `vm_agg_ap_gateway.py` | AP gateway / OpenWrt AP | `intentcontinuum.access_node.v1` | VictoriaMetrics（`ap_gateway.py` + `ap_snmp_gateway.py` 匯入） | 否 |

## Design Principles

- 有資料來源就補成和 `vm_aggregator.py` 接近的欄位名
- 沒有資料來源就不硬造欄位
- 儘量保留原本輸出欄位，另外補對齊欄位，避免破壞舊程式
- 最終正式輸出會清掉 `None`，避免把「上游沒提供」誤當成錯誤欄位

## 1. `vm_aggregator.py`

### Purpose

用於一般 Linux / Kubernetes node，輸出內容最完整，也是目前其他 aggregator 對齊的基準。

### Output Schema

- `schema = intentcontinuum.state.v6`

### Main Sources

- VictoriaMetrics
- Netdata
- DCGM exporter
- kube-state-metrics
- kubelet / cadvisor metrics

### Key Areas

- `cluster_semantic`
- `target_node_semantic.node_pressure`
- `target_node_semantic.node_pressure_instant`
- `target_node_semantic.node_compute_features`
- `target_node_semantic.gpu_pressure`
- `target_node_semantic.gpu_bound_features`
- `target_node_semantic.namespace_total_instant_local`

### Source Marking

- `target_node_semantic.node_pressure_instant.source = netdata`
- `target_node_semantic.node_compute_features.source = victoriametrics+node_exporter+netdata`
- `target_node_semantic.node_compute_features.cpu_compute.source = victoriametrics+node_exporter+netdata`
- `target_node_semantic.node_compute_features.ram_capacity.source = victoriametrics+node_exporter+netdata`
- `target_node_semantic.node_compute_features.data_movement.source = victoriametrics+node_exporter`
- `_debug` 預設不顯示，只有 `DEBUG_OUTPUT=1` 才會輸出

### Representative Fields

CPU / Load:

- `target_node_semantic.node_pressure_instant.cpu_usage_percent`
- `target_node_semantic.node_pressure_instant.cpu_user_percent`
- `target_node_semantic.node_pressure_instant.cpu_system_percent`
- `target_node_semantic.node_pressure_instant.cpu_idle_percent`
- `target_node_semantic.node_pressure_instant.cpu_iowait_percent`
- `target_node_semantic.node_pressure_instant.load_average.load1`
- `target_node_semantic.node_pressure_instant.load_average.load5`
- `target_node_semantic.node_pressure_instant.load_average.load15`

Memory / Swap:

- `target_node_semantic.node_pressure_instant.mem_total_bytes`
- `target_node_semantic.node_pressure_instant.mem_used_bytes`
- `target_node_semantic.node_pressure_instant.mem_free_bytes`
- `target_node_semantic.node_pressure_instant.memory_capacity.mem_available_bytes`
- `target_node_semantic.node_pressure_instant.memory_capacity.swap_used_bytes`
- `target_node_semantic.node_pressure_instant.memory_capacity.swap_free_bytes`

Disk / Temp:

- `target_node_semantic.node_pressure_instant.disk_root_usage_percent`
- `target_node_semantic.node_pressure_instant.cpu_temperature_c`

GPU:

- `target_node_semantic.gpu_pressure.gpus[]`
- `target_node_semantic.gpu_bound_features.gpu_compute.gpu_util_avg`
- `target_node_semantic.gpu_bound_features.gpu_compute.power_watts_avg`
- `target_node_semantic.gpu_bound_features.gpu_compute.gpu_temp_avg`
- `target_node_semantic.gpu_bound_features.vram_capacity.fb_total_bytes`
- `target_node_semantic.gpu_bound_features.data_movement.*`

### Dashboard Naming Guidance

- `Disk Use%` 建議明確標成 `Disk Use% (/)`
  - 對應欄位為 `target_node_semantic.node_pressure_instant.disk_root_usage_percent`
  - 語意是 root mount `/` 的使用率

- GPU 顯示建議以單卡欄位為主，不以 aggregate / avg 當主欄位
  - 適合多卡環境中只有單張卡高負載的情境
  - 建議主顯示由 `target_node_semantic.gpu_pressure.gpus[]` 自行展開
  - 例如：
    - `GPU0 Util% <- target_node_semantic.gpu_pressure.gpus[0].utilization_percent`
    - `GPU0 Mem Used(Bytes) <- target_node_semantic.gpu_pressure.gpus[0].fb_used_bytes`
    - `GPU0 Mem Total(Bytes) <- target_node_semantic.gpu_pressure.gpus[0].fb_total_bytes`
    - `GPU0 Temp(°C) <- target_node_semantic.gpu_pressure.gpus[0].temperature_c`
    - `GPU0 Power(W) <- target_node_semantic.gpu_pressure.gpus[0].power_watts`
  - `gpu_util_avg` / `gpu_temp_avg` / `power_watts_avg` 可保留在 JSON 中，但不建議作為主面板欄位
  - `gpu_bound_features` 目前只保留：
    - `gpu_compute`
    - `vram_capacity`
    - `data_movement`

### Current Notes

- `cpu_idle_percent` 已支援 fallback
  - 若 Netdata `system.cpu` 無 `idle` 維度，會用 `100 - 其他 CPU modes 總和` 回推
- `fb_used_percent` 已正規化為真百分比
  - 若上游回傳 `0~1` ratio，輸出前會自動乘 `100`
- GPU 顯存欄位目前以 `bytes` 為主
- `None` 欄位會在最終輸出前被清掉

### Typical Commands

```bash
python3 vm_aggregator.py
```

```bash
NODE=icclz1 K8S_NODE=icclz1 NAMESPACE=intent-lab python3 vm_aggregator.py
```

## 2. `vm_agg_rfsoc.py`

### Purpose

用於外部 RFSoC / PYNQ 節點。輸出 schema 已對齊 `intentcontinuum.state.v6`，但不包含 K8s workload / cluster overlay。

### Output Schema

- `schema = intentcontinuum.state.v6`

### Main Sources

- Netdata
- VictoriaMetrics
- SSH 讀取 PYNQ / XRT overlay status

### Key Areas

- `target_node_semantic.node_identity`
- `target_node_semantic.pl_status`
- `target_node_semantic.scheduling_capability`
- `target_node_semantic.node_pressure`
- `target_node_semantic.node_pressure_instant`
- `target_node_semantic.node_compute_features`
- `target_node_semantic.health`
- `_debug`

### Aligned Fields

已和 `vm_aggregator.py` 對齊的主要欄位：

- `node_pressure.cpu_usage_percent`
- `node_pressure.memory_usage_percent`
- `node_pressure.disk_root_usage_percent`
- `node_pressure_instant.cpu_usage_percent`
- `node_pressure_instant.cpu_user_percent`
- `node_pressure_instant.cpu_system_percent`
- `node_pressure_instant.cpu_idle_percent`
- `node_pressure_instant.cpu_iowait_percent`
- `node_pressure_instant.mem_total_bytes`
- `node_pressure_instant.mem_used_bytes`
- `node_pressure_instant.mem_free_bytes`
- `node_pressure_instant.mem_available_bytes`
- `node_pressure_instant.node_memory_working_set_bytes`
- `node_pressure_instant.memory_capacity.*`
- `node_pressure_instant.node_disk_io.read_bytes_per_s`
- `node_pressure_instant.node_disk_io.write_bytes_per_s`
- `node_compute_features.cpu_compute.*`
- `node_compute_features.ram_capacity.*`
- `node_compute_features.data_movement.*`

### Source Marking

- `target_node_semantic.node_pressure_instant.source = netdata_parent_host_scoped`
- `target_node_semantic.node_compute_features.source = netdata+victoriametrics+node_exporter`
- `target_node_semantic.node_compute_features.cpu_compute.source = netdata+victoriametrics`
- `target_node_semantic.node_compute_features.ram_capacity.source = netdata+node_exporter`
- `target_node_semantic.node_compute_features.data_movement.source = netdata+node_exporter`

### RFSoC-specific Fields

- `target_node_semantic.pl_status`
  - `xrt_device_ready`
  - `overlay_loaded`
  - `active_bitfile`
  - `ip_count`
  - `has_rfdc`
  - `has_dma`
  - `has_sysmon`
  - `temperature_c`
  - `vccint_v`
  - `vccaux_v`

- `target_node_semantic.scheduling_capability`
  - `can_run_fpga_overlay`
  - `can_run_rfdc_pipeline`
  - `can_run_dma_pipeline`

### Current Notes

- `cpu_idle_percent` 已補上與 `vm_aggregator.py` 相同的 fallback 行為
- 最終輸出也會清掉 `None`
- 因為 RFSoC 不是 K8s node，所以不會有 `cluster_semantic` 與 `namespace_total_instant_local`
- 若做 dashboard 命名，磁碟欄位也建議顯示為 `Disk Use% (/)`

### Typical Commands

```bash
python3 vm_agg_rfsoc.py
```

## 3. `vm_agg_ap_gateway.py`

### Purpose

用於 AP gateway / OpenWrt AP。主 schema 仍是 `intentcontinuum.access_node.v1`，但已補上一層和 `vm_aggregator.py` 接近的 node resource 欄位，方便前端或 dashboard 共用。

### Output Schema

- `schema = intentcontinuum.access_node.v1`

### Main Sources

- VictoriaMetrics
- 依賴 `ap_gateway.py` 匯入 `ap_wifi_*`
- 依賴 `ap_snmp_gateway.py` 匯入 `ap_node_*`

### Key Areas

- `access_node_semantic.wireless_access`
- `access_node_semantic.stations`
- `access_node_semantic.device_resource`
- `access_node_semantic.interface_traffic`
- `access_node_semantic.node_pressure`
- `access_node_semantic.node_pressure_instant`
- `access_node_semantic.node_compute_features`

### Aligned Fields

已補上的對齊欄位：

- `access_node_semantic.node_pressure.cpu_usage_percent`
- `access_node_semantic.node_pressure.memory_usage_percent`
- `access_node_semantic.node_pressure_instant.cpu_usage_percent`
- `access_node_semantic.node_pressure_instant.cpu_user_percent`
- `access_node_semantic.node_pressure_instant.cpu_system_percent`
- `access_node_semantic.node_pressure_instant.cpu_idle_percent`
- `access_node_semantic.node_pressure_instant.mem_total_bytes`
- `access_node_semantic.node_pressure_instant.mem_used_bytes`
- `access_node_semantic.node_pressure_instant.mem_free_bytes`
- `access_node_semantic.node_pressure_instant.memory_capacity.mem_available_bytes`
- `access_node_semantic.node_pressure_instant.memory_capacity.swap_used_bytes`
- `access_node_semantic.node_pressure_instant.memory_capacity.swap_total_bytes`
- `access_node_semantic.node_pressure_instant.memory_capacity.swap_free_bytes`
- `access_node_semantic.node_pressure_instant.load_average.load1`
- `access_node_semantic.node_pressure_instant.load_average.load5`
- `access_node_semantic.node_pressure_instant.load_average.load15`
- `access_node_semantic.node_compute_features.cpu_compute.*`
- `access_node_semantic.node_compute_features.ram_capacity.*`
- `access_node_semantic.node_compute_features.data_movement.*`

### Source Marking

- `access_node_semantic.node_pressure_instant.source = snmp_gateway+victoriametrics`
- `access_node_semantic.node_compute_features.source = snmp_gateway+victoriametrics`
- `access_node_semantic.node_compute_features.cpu_compute.source = snmp_gateway+victoriametrics`
- `access_node_semantic.node_compute_features.ram_capacity.source = snmp_gateway+victoriametrics`
- `access_node_semantic.node_compute_features.data_movement.source = snmp_gateway+victoriametrics`

### AP-specific Fields

- `wireless_access.station_count`
- `wireless_access.tx_bits_per_s`
- `wireless_access.rx_bits_per_s`
- `stations[]`
- `interface_traffic.admin_status`
- `interface_traffic.oper_status`

### Current Notes

- AP 來源沒有 `cpu_iowait_percent`
- AP 來源沒有 `disk_root_usage_percent`
- AP 來源沒有 `cpu_temperature_c`
- `mem_free_bytes` 是以 `mem_total - mem_used` 推算，比較像剩餘容量，不一定等於 Linux raw free memory
- 最終輸出會清掉 `None`
- AP 目前不適用 GPU 單卡欄位

### Typical Commands

```bash
python3 vm_agg_ap_gateway.py
```

## Common Field Alignment

下表是三支 aggregator 目前能共用的主要 node resource 欄位。

| 語意 | `vm_aggregator.py` | `vm_agg_rfsoc.py` | `vm_agg_ap_gateway.py` |
|---|---|---|---|
| CPU usage | `target_node_semantic.node_pressure_instant.cpu_usage_percent` | `target_node_semantic.node_pressure_instant.cpu_usage_percent` | `access_node_semantic.node_pressure_instant.cpu_usage_percent` |
| CPU user | `...cpu_user_percent` | `...cpu_user_percent` | `...cpu_user_percent` |
| CPU system | `...cpu_system_percent` | `...cpu_system_percent` | `...cpu_system_percent` |
| CPU idle | `...cpu_idle_percent` | `...cpu_idle_percent` | `...cpu_idle_percent` |
| CPU iowait | `...cpu_iowait_percent` | `...cpu_iowait_percent` | 無 |
| Load 1/5/15 | `...load_average.load1/5/15` | `...load_average.load1/5/15` | `...load_average.load1/5/15` |
| Mem total | `...mem_total_bytes` | `...mem_total_bytes` | `...mem_total_bytes` |
| Mem used | `...mem_used_bytes` | `...mem_used_bytes` | `...mem_used_bytes` |
| Mem free | `...mem_free_bytes` | `...mem_free_bytes` | `...mem_free_bytes` |
| Mem available | `...memory_capacity.mem_available_bytes` | `...memory_capacity.mem_available_bytes` | `...memory_capacity.mem_available_bytes` |
| Swap used | `...memory_capacity.swap_used_bytes` | `...memory_capacity.swap_used_bytes` | `...memory_capacity.swap_used_bytes` |
| Swap free | `...memory_capacity.swap_free_bytes` | `...memory_capacity.swap_free_bytes` | `...memory_capacity.swap_free_bytes` |
| Disk Use% (/) | `...disk_root_usage_percent` | `...disk_root_usage_percent` | 無 |
| CPU temp | `...cpu_temperature_c` | 無 | 無 |

## Recommended Dashboard Columns

如果前端要做與目前資料語意一致的面板，建議主欄位如下。

通用欄位：

- `CPU User%`
- `CPU System%`
- `CPU Idle%`
- `CPU IOWait%`
- `Load 1min`
- `Load 5min`
- `Load 15min`
- `Mem Total(MB)`
- `Mem Used(MB)`
- `Mem Free(MB)`
- `Mem Available(MB)`
- `Swap Used(MB)`
- `Swap Free(MB)`
- `Disk Use% (/)`
- `CPU Temp(°C)`

GPU 欄位：

- 優先使用單卡欄位
- 不建議以 aggregate / avg 作為主欄位

建議形式：

- `GPU0 Util%`
- `GPU0 Mem Used(MB)`
- `GPU0 Mem Total(MB)`
- `GPU0 Temp(°C)`
- `GPU0 Power(W)`

多卡時依序展開：

- `GPU1 Util%`
- `GPU1 Mem Used(MB)`
- `GPU1 Mem Total(MB)`
- `GPU1 Temp(°C)`
- `GPU1 Power(W)`

對應來源：

- `target_node_semantic.gpu_pressure.gpus[0].utilization_percent`
- `target_node_semantic.gpu_pressure.gpus[0].fb_used_bytes`
- `target_node_semantic.gpu_pressure.gpus[0].fb_total_bytes`
- `target_node_semantic.gpu_pressure.gpus[0].temperature_c`
- `target_node_semantic.gpu_pressure.gpus[0].power_watts`

## Known Gaps

### `vm_agg_ap_gateway.py`

- 無 GPU 指標
- 無 CPU temperature
- 無 disk root usage percent
- 無 CPU iowait percent

### `vm_agg_rfsoc.py`

- 無 K8s cluster / namespace overlay
- 無 GPU/DCGM 指標
- 以外部節點為主，非容器排程節點

### `vm_aggregator.py`

- 若上游缺值，欄位會被省略而不是輸出 `null`
- K8s `capacity/allocatable` 與實體 GPU 存在可能不一致

## Validation Status

已完成：

- `vm_aggregator.py` live 執行驗證
- `vm_agg_rfsoc.py` live 執行驗證
- `vm_agg_ap_gateway.py` live 執行驗證
- 三支語法檢查

已觀察到：

- `vm_agg_ap_gateway.py` 對齊欄位有值且合理
- `vm_agg_rfsoc.py` 對齊欄位有值且合理
- `vm_aggregator.py` CPU idle fallback、CPU temperature、GPU fb used percent 已驗證

## Recommended Usage

- 如果目標是 K8s 節點與 GPU node，用 `vm_aggregator.py`
- 如果目標是外部 RFSoC 節點，用 `vm_agg_rfsoc.py`
- 如果目標是 AP / OpenWrt gateway，用 `vm_agg_ap_gateway.py`
- 如果前端要共用資源面板，優先接：
  - `node_pressure`
  - `node_pressure_instant`
  - `node_compute_features`
