from typing import List, Literal

from pydantic import BaseModel


class FanCycleCommandPreview(BaseModel):
    smoke_test: str
    full_experiment: str


class FanCycleRunInfo(BaseModel):
    run_id: str
    status: str
    target_node: str
    gpu_name: str
    workload: str
    cycles: int
    current_cycle: int
    current_phase: str
    elapsed_seconds: float
    focus_pod: str
    target_url: str


class FanCycleConfig(BaseModel):
    normal_hold_seconds: int
    fault_hold_seconds: int
    recovery_stable_seconds: int
    recovery_max_seconds: int
    fixed_fan_pct: int
    normal_temp_min_c: float
    normal_temp_max_c: float
    fault_temp_target_c: float
    bg_size: int
    bg_duty: float
    bg_period_ms: int


class FanCycleCurrentMetrics(BaseModel):
    gpu_temp_c: float
    fan_pct: float
    sm_clock_mhz: float
    gpu_util_pct: float
    server_latency_ms: float
    e2e_latency_ms: float


class FanCyclePhaseSummary(BaseModel):
    cycle_index: int
    phase: str
    gpu_temp_c_mean: float
    gpu_temp_c_p95: float
    gpu_fan_pct_mean: float
    gpu_util_pct_mean: float
    gpu_clock_mhz_mean: float
    server_latency_ms_p95: float
    e2e_latency_ms_p95: float


class FanCycleTimeseriesPoint(BaseModel):
    time: str
    elapsed_s: float
    cycle_index: int
    phase: str
    gpu_temp: float
    fan_pct: float
    sm_clock: float
    gpu_util: float
    server_latency: float
    e2e_latency: float


class FanCycleEvent(BaseModel):
    time: str
    level: str
    phase: str
    event: str
    detail: str
    message: str


class FanCycleLatestResponse(BaseModel):
    schema_name: str
    generated_at: int
    run: FanCycleRunInfo
    config: FanCycleConfig
    current: FanCycleCurrentMetrics
    command_preview: FanCycleCommandPreview
    phase_summary: List[FanCyclePhaseSummary]
    timeseries: List[FanCycleTimeseriesPoint]
    events: List[FanCycleEvent]


class FanCycleLiveResponse(BaseModel):
    schema_name: str
    generated_at: int
    run: FanCycleRunInfo
    current: FanCycleCurrentMetrics


class YoloDemoStatusResponse(BaseModel):
    schema_name: str
    generated_at: int
    status: Literal["idle", "starting", "running", "stopping", "stopped", "error"]
    run_id: str
    namespace: str
    focus_deploy: str
    bg_deploy: str
    focus_pod: str
    target_url: str
    target_mode: str
    node_name: str
    measurement_pid: int
    bgload_pid: int
    fan_mode: Literal["GPU_DEFAULT", "FIXED_5", "FIXED_15", "FIXED_20", "FIXED_25"]
    started_at: int
    message: str


class YoloDemoEvent(BaseModel):
    time: str
    level: Literal["info", "warn", "critical"]
    event: str
    message: str


class YoloDemoEventsResponse(BaseModel):
    schema_name: str
    generated_at: int
    events: List[YoloDemoEvent]
