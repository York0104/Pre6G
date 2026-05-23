from fastapi import APIRouter, HTTPException

from app.schemas.full_metrics import FullMetricsListResponse, FullMetricsResponse
from app.services.cache_service import SimpleTTLCache
from app.services.full_metrics_service import FullMetricsService

router = APIRouter(prefix="/api/v1/full-metrics", tags=["full-metrics"])

cache = SimpleTTLCache()
full_metrics_service = FullMetricsService(cache=cache)


@router.get("", response_model=FullMetricsListResponse)
def get_all_full_metrics() -> FullMetricsListResponse:
    return full_metrics_service.get_all_metrics()


@router.get("/{node_name}", response_model=FullMetricsResponse)
def get_node_full_metrics(node_name: str) -> FullMetricsResponse:
    try:
        return full_metrics_service.get_node_metrics(node_name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
