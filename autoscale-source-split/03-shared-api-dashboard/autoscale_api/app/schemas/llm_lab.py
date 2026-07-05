from typing import Optional

from pydantic import BaseModel, Field


class LlmInferenceRequest(BaseModel):
    namespace: str
    workload: str
    prompt: str = Field(min_length=1, max_length=8192)
    max_tokens: int = Field(default=128, ge=1, le=512)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class LlmInferenceResponse(BaseModel):
    schema: str
    ts: int
    namespace: str
    workload: str
    target_service: str
    model: Optional[str] = None
    http_status: int
    latency_seconds: float
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    response_text: Optional[str] = None


class LlmSmokeBenchmarkRequest(BaseModel):
    namespace: str
    workload: str


class LlmBenchmarkRequest(BaseModel):
    namespace: str
    workload: str


class LlmOfflineThroughputRequest(BaseModel):
    namespace: str
    workload: str
    profile_id: str


class LlmBenchmarkRunRequest(BaseModel):
    namespace: str
    workload: str
    profile_id: str


class LlmBenchmarkResponse(BaseModel):
    schema: str
    ts: int
    run_id: str
    namespace: str
    workload: str
    profile: str
    profile_id: Optional[str] = None
    request_count: int
    max_tokens: int
    temperature: float
    concurrency: Optional[int] = None
    status: str
    completed_requests: int
    failed_requests: int
    run_elapsed_seconds: Optional[float] = None
    request_throughput_rps: Optional[float] = None
    aggregate_prompt_tps: Optional[float] = None
    aggregate_generation_tps: Optional[float] = None
    aggregate_total_tps: Optional[float] = None
    latency_p50_seconds: Optional[float] = None
    latency_p95_seconds: Optional[float] = None
    mean_latency_seconds: Optional[float] = None
    mean_prompt_tokens: Optional[float] = None
    mean_completion_tokens: Optional[float] = None
    mean_total_tokens: Optional[float] = None
    mean_ttft_seconds: Optional[float] = None
    p95_ttft_seconds: Optional[float] = None
    mean_tpot_seconds: Optional[float] = None
    p95_tpot_seconds: Optional[float] = None
    mean_itl_seconds: Optional[float] = None
    p95_itl_seconds: Optional[float] = None


class LlmRunHistoryItem(BaseModel):
    ts: int
    event_type: str
    runtime: Optional[str] = None
    benchmark_mode: Optional[str] = None
    namespace: str
    workload: str
    status: str
    run_id: Optional[str] = None
    profile: Optional[str] = None
    profile_id: Optional[str] = None
    model: Optional[str] = None
    latency_seconds: Optional[float] = None
    prompt_char_count: Optional[int] = None
    prompt_sha256: Optional[str] = None
    prompt_tokens: Optional[float] = None
    completion_tokens: Optional[float] = None
    total_tokens: Optional[float] = None
    finish_reason: Optional[str] = None
    request_count: Optional[int] = None
    concurrency: Optional[int] = None
    completed_requests: Optional[int] = None
    failed_requests: Optional[int] = None
    run_elapsed_seconds: Optional[float] = None
    request_throughput_rps: Optional[float] = None
    aggregate_prompt_tps: Optional[float] = None
    aggregate_generation_tps: Optional[float] = None
    aggregate_total_tps: Optional[float] = None
    latency_p50_seconds: Optional[float] = None
    latency_p95_seconds: Optional[float] = None
    mean_latency_seconds: Optional[float] = None
    mean_prompt_tokens: Optional[float] = None
    mean_completion_tokens: Optional[float] = None
    mean_total_tokens: Optional[float] = None
    prompt_tps_mean: Optional[float] = None
    prompt_tps_stddev: Optional[float] = None
    generation_tps_mean: Optional[float] = None
    generation_tps_stddev: Optional[float] = None
    prompt_generation_tps_mean: Optional[float] = None
    prompt_generation_tps_stddev: Optional[float] = None
    duration_seconds: Optional[float] = None
    observed_at_ts: Optional[int] = None
    gpu_contended: Optional[bool] = None
    error_summary: Optional[str] = None


class LlmRunHistoryResponse(BaseModel):
    schema: str
    ts: int
    count: int
    items: list[LlmRunHistoryItem]


LlmSmokeBenchmarkResponse = LlmBenchmarkResponse


class LlmBenchmarkProgressBucket(BaseModel):
    second: int
    completed_requests: int = 0
    failed_requests: int = 0
    prompt_tokens: float = 0.0
    completion_tokens: float = 0.0
    total_tokens: float = 0.0


class LlmBenchmarkProgressSnapshot(BaseModel):
    elapsed_seconds: float
    completed_requests: int
    failed_requests: int
    prompt_tokens_so_far: float
    completion_tokens_so_far: float
    total_tokens_so_far: float
    current_request_throughput_rps: float
    current_prompt_tps: float
    current_generation_tps: float
    current_total_tps: float
    buckets: list[LlmBenchmarkProgressBucket]


class LlmBenchmarkRunStatusResponse(BaseModel):
    schema: str
    ts: int
    run_id: str
    namespace: str
    workload: str
    profile: str
    profile_id: str
    status: str
    request_count: int
    concurrency: int
    max_tokens: int
    temperature: float
    started_ts: int
    finished_ts: Optional[int] = None
    progress: LlmBenchmarkProgressSnapshot
    result: Optional[LlmBenchmarkResponse] = None
    error: Optional[str] = None


class LlmBenchmarkRunStartResponse(BaseModel):
    schema: str
    ts: int
    run_id: str
    namespace: str
    workload: str
    profile: str
    profile_id: str
    status: str


class LlmBenchmarkRunCancelResponse(BaseModel):
    schema: str
    ts: int
    run_id: str
    status: str


class LlamacppOfflineBenchmarkRunRequest(BaseModel):
    profile: str


class LlamacppOfflineBenchmarkProfile(BaseModel):
    profile_id: str
    display_name: str
    description: str
    runtime: str
    benchmark_mode: str
    n_prompt: int
    n_gen: int
    pg_pair: Optional[str] = None
    n_depth: int
    batch_size: int
    ubatch_size: int
    repetitions: int
    flash_attention: str
    gpu_layers: int


class LlamacppOfflineBenchmarkProfilesResponse(BaseModel):
    schema: str
    ts: int
    runtime: str
    benchmark_mode: str
    profiles: list[LlamacppOfflineBenchmarkProfile]


class LlamacppOfflineGpuProcess(BaseModel):
    pid: Optional[int] = None
    process_name: Optional[str] = None
    used_memory: Optional[str] = None


class LlamacppOfflineRuntimeOverview(BaseModel):
    runtime: str
    benchmark_mode: str
    runtime_image: Optional[str] = None
    runtime_image_tag: Optional[str] = None
    llama_cpp_ref: Optional[str] = None
    llama_cpp_commit: Optional[str] = None
    cuda_version: Optional[str] = None
    gpu_model: Optional[str] = None
    gpu_arch: Optional[str] = None
    gpu_resource_request: Optional[str] = None
    namespace: str
    target_pod: str
    node_name: Optional[str] = None
    model_name: Optional[str] = None
    model_source: Optional[str] = None
    gguf_filename: Optional[str] = None
    gguf_path: Optional[str] = None
    gguf_sha256: Optional[str] = None
    quantization: Optional[str] = None
    gpu_layers: Optional[str] = None


class LlamacppOfflineBenchmarkResult(BaseModel):
    schema: str
    ts: int
    run_id: str
    runtime: str
    benchmark_mode: str
    profile: str
    profile_id: str
    status: str
    namespace: str
    target_pod: str
    node_name: Optional[str] = None
    runtime_overview: LlamacppOfflineRuntimeOverview
    observed_at_ts: Optional[int] = None
    started_at_ts: Optional[int] = None
    completed_at_ts: Optional[int] = None
    duration_seconds: Optional[float] = None
    prompt_tps_mean: Optional[float] = None
    prompt_tps_stddev: Optional[float] = None
    generation_tps_mean: Optional[float] = None
    generation_tps_stddev: Optional[float] = None
    prompt_generation_tps_mean: Optional[float] = None
    prompt_generation_tps_stddev: Optional[float] = None
    waiting_requests: Optional[float] = None
    kv_cache_usage_percent: Optional[float] = None
    n_prompt: int
    n_gen: int
    n_depth: int
    batch_size: int
    ubatch_size: int
    n_gpu_layers: int
    repetitions: int
    flash_attention: str
    gpu_processes_before: list[LlamacppOfflineGpuProcess] = Field(default_factory=list)
    gpu_process_count_before: int = 0
    gpu_contended: bool = False
    gpu_preflight_status: str
    preflight_warning: Optional[str] = None
    error_summary: Optional[str] = None


class LlamacppOfflineBenchmarkRunStateResponse(BaseModel):
    schema: str
    ts: int
    run_id: str
    runtime: str
    benchmark_mode: str
    profile: str
    profile_id: str
    status: str
    namespace: str
    target_pod: str
    node_name: Optional[str] = None
    started_at_ts: Optional[int] = None
    completed_at_ts: Optional[int] = None
    result: Optional[LlamacppOfflineBenchmarkResult] = None
    error: Optional[str] = None


class LlamacppOfflineBenchmarkRunStartResponse(BaseModel):
    schema: str
    ts: int
    run_id: str
    runtime: str
    benchmark_mode: str
    profile: str
    profile_id: str
    status: str
    namespace: str
    target_pod: str


class LlamacppOfflineBenchmarkRunsResponse(BaseModel):
    schema: str
    ts: int
    count: int
    items: list[LlamacppOfflineBenchmarkRunStateResponse]
