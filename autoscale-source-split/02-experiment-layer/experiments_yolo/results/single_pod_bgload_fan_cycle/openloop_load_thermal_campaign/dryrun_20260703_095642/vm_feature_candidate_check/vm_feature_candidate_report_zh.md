# VM-derived telemetry feature candidate check

- input_root: `autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle/openloop_load_thermal_campaign/dryrun_20260703_095642`
- calibration_runs: `9`
- rows: `537`
- numeric_vmagg_features: `226`
- candidate_load_features: `27`

此檢查只用 normal-cooling calibration first pass。它用來判斷 VM-derived telemetry 是否可進入下一階段 load-conditioned model 的候選特徵，不代表已完成 feature importance，也不代表未知根因泛化。

## Recommended Load Candidates

| feature | role | missing | unique | corr_with_offered_rps | median_by_offered_rps |
|---|---|---:|---:|---:|---|
| `vmagg.target_node_semantic.node_compute_features.cpu_compute.cpu_user_percent` | `cpu_load_candidate` | 0.000 | 332 | 0.42536107662646905 | `0.5:6.779661; 1.0:6.976744; 1.5:8.129045999999999` |
| `vmagg.target_node_semantic.node_pressure_instant.cpu_user_percent` | `cpu_load_candidate` | 0.000 | 332 | 0.42536107662646905 | `0.5:6.779661; 1.0:6.976744; 1.5:8.129045999999999` |
| `vmagg.target_node_semantic.gpu_bound_features.gpu_compute.gpu_util_avg` | `gpu_load_candidate` | 0.000 | 9 | 0.3016100906910279 | `0.5:0.0; 1.0:17.0; 1.5:23.0` |
| `vmagg.cluster_semantic.namespace_total.cpu_cores_rate` | `cpu_load_candidate` | 0.000 | 54 | 0.2821538795055933 | `0.5:0.1059345000000235; 1.0:0.159678899999983; 1.5:0.2766352000000097` |
| `vmagg.target_node_semantic.node_pressure_instant.load_average.load15` | `cpu_load_candidate` | 0.000 | 32 | 0.18340830862341617 | `0.5:0.76; 1.0:0.81; 1.5:0.88` |
| `vmagg.target_node_semantic.node_compute_features.cpu_compute.load15` | `cpu_load_candidate` | 0.000 | 21 | 0.17676600465304335 | `0.5:0.76; 1.0:0.8; 1.5:0.85` |
| `vmagg.target_node_semantic.node_compute_features.ram_capacity.pgmajfault_per_s` | `memory_load_candidate` | 0.002 | 2 | -0.1698191105107578 | `0.5:0.0; 1.0:0.0; 1.5:0.0` |
| `vmagg.target_node_semantic.node_compute_features.ram_capacity.memory_pressure_waiting_seconds_per_s` | `memory_load_candidate` | 0.002 | 2 | -0.16981911051075738 | `0.5:0.0; 1.0:0.0; 1.5:0.0` |
| `vmagg.target_node_semantic.node_pressure_instant.cpu_usage_percent` | `cpu_load_candidate` | 0.000 | 459 | 0.15671960614101674 | `0.5:10.7329844; 1.0:10.335916749999999; 1.5:11.56599525` |
| `vmagg.target_node_semantic.node_compute_features.cpu_compute.cpu_system_percent` | `cpu_load_candidate` | 0.000 | 257 | -0.1514147003249369 | `0.5:2.748691; 1.0:2.325581; 1.5:2.3225845` |
| `vmagg.target_node_semantic.node_pressure_instant.cpu_system_percent` | `cpu_load_candidate` | 0.000 | 257 | -0.1514147003249369 | `0.5:2.748691; 1.0:2.325581; 1.5:2.3225845` |
| `vmagg.target_node_semantic.node_pressure_instant.load_average.load5` | `cpu_load_candidate` | 0.000 | 51 | 0.140160790973478 | `0.5:0.88; 1.0:0.99; 1.5:1.07` |
| `vmagg.target_node_semantic.node_compute_features.cpu_compute.load5` | `cpu_load_candidate` | 0.000 | 37 | 0.1280977128641798 | `0.5:0.87; 1.0:0.99; 1.5:1.06` |
| `vmagg.target_node_semantic.node_compute_features.ram_capacity.memory_pressure_stalled_seconds_per_s` | `memory_load_candidate` | 0.002 | 2 | 0.11988613019672352 | `0.5:0.0; 1.0:0.0; 1.5:0.0` |
| `vmagg.target_node_semantic.node_compute_features.cpu_compute.load1` | `cpu_load_candidate` | 0.000 | 44 | -0.09348982568456231 | `0.5:1.34; 1.0:1.09; 1.5:1.065` |
| `vmagg.target_node_semantic.node_compute_features.ram_capacity.mem_free_bytes` | `memory_load_candidate` | 0.000 | 473 | -0.07676377995728038 | `0.5:56732124446.0; 1.0:56722624347.5; 1.5:56730939555.5` |
| `vmagg.target_node_semantic.node_compute_features.ram_capacity.mem_total_bytes` | `memory_load_candidate` | 0.000 | 113 | 0.02997709352748068 | `0.5:67357437434.0; 1.0:67357437748.0; 1.5:67357437800.5` |
| `vmagg.target_node_semantic.node_compute_features.ram_capacity.memory_usage_percent` | `memory_load_candidate` | 0.000 | 55 | -0.028763421114324082 | `0.5:7.135435292869974; 1.0:7.150829322564789; 1.5:7.134571792093092` |
| `vmagg.target_node_semantic.node_pressure_instant.load_average.load1` | `cpu_load_candidate` | 0.000 | 78 | -0.02657311414682408 | `0.5:1.33; 1.0:1.08; 1.5:1.18` |
| `vmagg.target_node_semantic.node_pressure_instant.node_memory_working_set_bytes` | `memory_load_candidate` | 0.000 | 503 | 0.023171099948389028 | `0.5:4059013578.0; 1.0:4067481353.5; 1.5:4058280099.5` |

## Target / Context Signals

以下欄位可作為 thermal/clock/power target 或 context，但不應與 offered load 混為同一類外部 demand feature。

| feature | missing | median_by_offered_rps |
|---|---:|---|
| `vmagg.target_node_semantic.gpu_bound_features.gpu_compute.energy_mj_sum` | 0.000 | `0.5:8486834473.0; 1.0:8491954648.0; 1.5:8497824844.0` |
| `vmagg.target_node_semantic.node_pressure_instant.node_disk_io.read_bytes_per_s` | 0.000 | `0.5:84997.04832; 1.0:403350.3232; 1.5:165104.23552` |
| `vmagg.target_node_semantic.node_pressure_instant.node_disk_io.write_bytes_per_s` | 0.000 | `0.5:52609.62816; 1.0:49243.494399999996; 1.5:43748.188160000005` |
| `vmagg.target_node_semantic.node_compute_features.data_movement.disk_read_bytes_per_s` | 0.002 | `0.5:276889.6; 1.0:437862.4; 1.5:299827.2` |
| `vmagg.target_node_semantic.node_compute_features.data_movement.disk_write_bytes_per_s` | 0.002 | `0.5:67993.6; 1.0:63078.4; 1.5:57344.0` |
| `vmagg.target_node_semantic.gpu_bound_features.gpu_compute.mem_clock_mhz_avg` | 0.000 | `0.5:5005.0; 1.0:5005.0; 1.5:5005.0` |
| `vmagg.target_node_semantic.gpu_bound_features.gpu_compute.sm_clock_mhz_avg` | 0.000 | `0.5:1923.0; 1.0:1936.0; 1.5:1923.0` |
| `vmagg.target_node_semantic.gpu_bound_features.gpu_compute.power_watts_avg` | 0.000 | `0.5:76.56; 1.0:85.834; 1.5:78.227` |
| `vmagg.target_node_semantic.gpu_bound_features.gpu_compute.gpu_temp_avg` | 0.000 | `0.5:60.0; 1.0:59.0; 1.5:62.0` |
| `vmagg.target_node_semantic.node_compute_features.cpu_compute.cpu_temperature_c` | 0.000 | `0.5:38.0; 1.0:40.0; 1.5:40.0` |
| `vmagg.target_node_semantic.node_pressure_instant.cpu_temperature_c` | 0.000 | `0.5:38.0; 1.0:40.0; 1.5:40.0` |
| `vmagg.target_node_semantic.gpu_bound_features.gpu_compute.pstate_avg` | 0.000 | `0.5:2.0; 1.0:2.0; 1.5:2.0` |
| `vmagg.target_node_semantic.gpu_bound_features.gpu_compute.pstate_min` | 0.000 | `0.5:2.0; 1.0:2.0; 1.5:2.0` |
| `vmagg.target_node_semantic.node_pressure.disk_root_usage_percent` | 0.000 | `0.5:20.260649989668742; 1.0:20.260746442654167; 1.5:20.260866907142272` |
| `vmagg.target_node_semantic.node_pressure_instant.disk_root_usage_percent` | 0.000 | `0.5:20.260649989668742; 1.0:20.260746442654167; 1.5:20.260866907142272` |
| `vmagg.target_node_semantic.gpu_bound_features.gpu_compute.power_violation_ns_sum` | 0.000 | `0.5:0.0; 1.0:0.0; 1.5:0.0` |
| `vmagg.target_node_semantic.gpu_bound_features.gpu_compute.thermal_violation_ns_sum` | 0.000 | `0.5:0.0; 1.0:0.0; 1.5:0.0` |

## Method Notes

- External demand 仍以 open-loop `offered_rps` / scheduled arrivals 為準。
- `completed RPS`、success rate、latency history 屬 observed service state，不可取代 offered load。
- fan mode、phase、run ID、cycle ID、absolute elapsed time 不列入 primary operational features。
- 目前只有 3 個 short calibration levels；相關係數只作 sanity check，不作正式 feature importance。
