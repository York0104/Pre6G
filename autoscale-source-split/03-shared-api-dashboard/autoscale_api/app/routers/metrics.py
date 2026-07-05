from fastapi import APIRouter, Response

from app.routers.llm_lab import llm_lab_service

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
def get_prometheus_metrics() -> Response:
    payload = llm_lab_service.render_prometheus_metrics()
    return Response(
        content=payload,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
