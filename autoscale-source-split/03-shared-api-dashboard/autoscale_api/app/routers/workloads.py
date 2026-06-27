from fastapi import APIRouter, HTTPException, Query

from app.schemas.workload import WorkloadListResponse, WorkloadStatusResponse
from app.services.cache_service import SimpleTTLCache
from app.services.workload_status_service import WorkloadStatusService

router = APIRouter(prefix="/api/v1/workloads", tags=["workloads"])

cache = SimpleTTLCache()
status_service = WorkloadStatusService(cache=cache)


@router.get("", response_model=WorkloadListResponse)
def get_workloads(
    namespace: str | None = Query(default=None, description="Optional namespace override"),
) -> WorkloadListResponse:
    return status_service.get_workloads(namespace=namespace)


@router.get("/{namespace}/{workload}/status", response_model=WorkloadStatusResponse)
def get_workload_status(namespace: str, workload: str) -> WorkloadStatusResponse:
    try:
        return status_service.get_workload_status(namespace=namespace, workload=workload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
