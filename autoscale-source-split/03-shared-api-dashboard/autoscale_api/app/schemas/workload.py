from typing import List, Optional

from pydantic import BaseModel


class WorkloadIdentity(BaseModel):
    namespace: str
    workload: str
    runtime: str
    model_name: Optional[str] = None
    served_model_id: Optional[str] = None
    runtime_image: Optional[str] = None
    runtime_version: Optional[str] = None


class WorkloadReplicaSummary(BaseModel):
    desired: int
    ready: int
    metrics_available: int
    metrics_unavailable: int


class WorkloadReplicaStatus(BaseModel):
    pod: str
    node_name: str
    status: str
    owner_resolution: str
    pod_phase: Optional[str] = None
    ready_condition: Optional[bool] = None
    metrics_observed_ts: Optional[int] = None
    metrics_freshness_seconds: Optional[float] = None
    generation_tokens_per_second: Optional[float] = None
    prompt_tokens_per_second: Optional[float] = None
    waiting_requests: Optional[float] = None
    kv_cache_usage_percent: Optional[float] = None


class WorkloadAggregateMetrics(BaseModel):
    generation_tokens_per_second: Optional[float] = None
    prompt_tokens_per_second: Optional[float] = None
    waiting_requests: Optional[float] = None
    kv_cache_usage_percent_max: Optional[float] = None


class WorkloadStatusPayload(BaseModel):
    schema: str
    ts: int
    freshness_seconds: float
    query_window_seconds: int
    metrics_observed_ts: Optional[int] = None
    scrape_source: str = "vmagent -> VictoriaMetrics"
    status: str
    identity: WorkloadIdentity
    replica_summary: WorkloadReplicaSummary
    replicas: List[WorkloadReplicaStatus]
    aggregate: WorkloadAggregateMetrics


class WorkloadStatusResponse(WorkloadStatusPayload):
    pass


class WorkloadListItem(BaseModel):
    namespace: str
    workload: str
    runtime: str
    model_name: Optional[str] = None
    runtime_image: Optional[str] = None
    runtime_version: Optional[str] = None
    nodes: List[str] = []
    status: str
    desired_replicas: int
    ready_replicas: int
    generation_tokens_per_second: Optional[float] = None
    prompt_tokens_per_second: Optional[float] = None
    waiting_requests: Optional[float] = None
    kv_cache_usage_percent_max: Optional[float] = None


class WorkloadListResponse(BaseModel):
    schema: str
    ts: int
    freshness_seconds: float
    query_window_seconds: int
    count: int
    workloads: List[WorkloadListItem]
