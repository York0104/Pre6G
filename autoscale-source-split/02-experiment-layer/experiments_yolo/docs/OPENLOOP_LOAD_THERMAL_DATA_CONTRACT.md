# Open-loop Load Thermal Data Contract

## Run Manifest

每個 run 必須保存 `run_manifest.json`，至少包含：

- `run_id`
- experiment timestamp
- git revision
- node / GPU identity
- container image / YOLO model
- endpoint and payload configuration
- offered-load profile
- client configuration
- background workload configuration
- cooling condition metadata
- operator-configured safety threshold
- start / stop / abort reason
- telemetry source availability
- cleanup / restore result

Normal-only live smoke 或 calibration 的每個 sub-run 也必須保存自己的 `run_manifest.json`，其中 cooling condition 固定為 `normal_cooling`，並明確記錄：

- `no_fan_control_executed = true`
- `no_coolercontrol_executed = true`
- `no_kubernetes_scale_restart_delete_executed = true`
- offered load profile
- telemetry runtime
- safety threshold

## Open-loop Client Raw Log

必要欄位：

- `req_id`
- `schedule_index`
- `scheduled_elapsed_s`
- `scheduled_time_iso`
- `send_time_iso`
- `complete_time_iso`
- `schedule_delay_ms`
- `target_rps`
- `profile_name`
- `inflight_at_schedule`
- `launch_status`
- `success`
- `status_code`
- `error_type`
- `error_msg`
- `e2e_latency_ms`
- `server_latency_ms`
- `server_total_latency_ms`
- `server_time`
- `server_pod_name`
- `server_node_name`
- `model`
- `device`
- `imgsz`
- `filename`

## Open-loop Arrival-Binned 1s Summary

必要欄位：

- `offered_rps`
- `scheduled_request_count`
- `launched_request_count`
- `dropped_max_inflight_count`
- `arrival_bin_completed_count`
- `arrival_bin_successful_completion_count`
- `arrival_bin_completion_fraction`
- `arrival_bin_success_fraction`
- `fail_rate`
- `timeout_rate`
- `inflight_count_max`
- `client_backlog_or_schedule_miss`
- `latency_p50`
- `latency_p95`
- `latency_p99`

Arrival-binned summary 以 `scheduled_elapsed_s` 分桶。`offered_rps` 是 scheduled arrivals；`arrival_bin_completed_count` 是該 arrival bin 內排程之 request 最後完成的數量，不得命名為 realized completed RPS。

## Open-loop Completion-Binned 1s Summary

必要欄位：

- `realized_completed_rps`
- `completed_request_count`
- `successful_completion_count`
- `failed_completion_count`
- `timeout_completion_count`
- `completion_success_fraction`
- `completion_timeout_fraction`
- `latency_p50`
- `latency_p95`
- `latency_p99`

Completion-binned summary 以 `complete_elapsed_s` 分桶，用於 realized service activity。Latency quantile 僅基於該 completion bin 內的 successful completions。

## Telemetry Gap Policy

P-state、throttle reason、performance-cap reason、power-limit state、GPU process-level metrics 若無法取得，必須在 manifest 與 report 中標記為 telemetry gap，不得補值或推論成已觀測事實。

## Safety / Abort Record

每個 normal-only live sub-run 必須輸出：

- `safety_abort_record.json`
- `safety_abort_record.jsonl`
- `telemetry_availability_summary.json`

Abort condition 至少包含：

- missing GPU telemetry
- GPU temperature exceeds `operator_max_gpu_temp_c`
- timeout burst
- error burst
- max-inflight saturation
- missing request client output
- missing arrival/completion summary

## Calibration Summary

`offline_normal_load_calibration_analysis.py` 輸出：

- `normal_load_calibration_summary.csv`
- `normal_load_calibration_report_zh.md`
- `analysis_manifest.json`

欄位包含 offered RPS、drop ratio、completion throughput、timeout/error rate、latency quantiles、GPU temperature、SM clock、power 與 utilization。completed RPS 只代表 realized service activity，不得視為 offered demand。
