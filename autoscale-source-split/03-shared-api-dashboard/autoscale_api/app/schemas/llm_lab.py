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
    target_url: str
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
    mean_latency_seconds: Optional[float] = None
    mean_prompt_tokens: Optional[float] = None
    mean_completion_tokens: Optional[float] = None
    mean_total_tokens: Optional[float] = None


class LlmRunHistoryItem(BaseModel):
    ts: int
    event_type: str
    namespace: str
    workload: str
    status: str
    run_id: Optional[str] = None
    profile: Optional[str] = None
    profile_id: Optional[str] = None
    model: Optional[str] = None
    latency_seconds: Optional[float] = None
    prompt_tokens: Optional[float] = None
    completion_tokens: Optional[float] = None
    total_tokens: Optional[float] = None
    finish_reason: Optional[str] = None
    prompt_preview: Optional[str] = None
    request_count: Optional[int] = None
    concurrency: Optional[int] = None
    completed_requests: Optional[int] = None
    failed_requests: Optional[int] = None
    mean_latency_seconds: Optional[float] = None
    mean_prompt_tokens: Optional[float] = None
    mean_completion_tokens: Optional[float] = None
    mean_total_tokens: Optional[float] = None


class LlmRunHistoryResponse(BaseModel):
    schema: str
    ts: int
    count: int
    items: list[LlmRunHistoryItem]


LlmSmokeBenchmarkResponse = LlmBenchmarkResponse
