from typing import Any, Dict, List

from pydantic import BaseModel


class FullMetricsNodePayload(BaseModel):
    node_name: str
    node_type: str
    aggregator: str
    payload: Dict[str, Any]


class FullMetricsListResponse(BaseModel):
    schema: str
    ts: int
    count: int
    ok_count: int
    error_count: int
    nodes: List[FullMetricsNodePayload]


class FullMetricsResponse(BaseModel):
    schema: str
    ts: int
    node: FullMetricsNodePayload
