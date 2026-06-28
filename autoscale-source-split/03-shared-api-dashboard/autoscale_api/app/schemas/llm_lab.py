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


class LlmSmokeBenchmarkResponse(BaseModel):
    schema: str
    ts: int
    run_id: str
    namespace: str
    workload: str
    profile: str
    request_count: int
    max_tokens: int
    temperature: float
    status: str
    completed_requests: int
    failed_requests: int
    mean_latency_seconds: Optional[float] = None
    mean_prompt_tokens: Optional[float] = None
    mean_completion_tokens: Optional[float] = None
    mean_total_tokens: Optional[float] = None
