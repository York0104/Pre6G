from fastapi import APIRouter, HTTPException

from app.schemas.experiment import (
    FanCycleLatestResponse,
    FanCycleLiveResponse,
    YoloDemoEventsResponse,
    YoloDemoStatusResponse,
)
from app.services.cache_service import SimpleTTLCache
from app.services.fan_cycle_experiment_service import FanCycleExperimentService
from app.services.yolo_demo_service import YoloDemoService

router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])

cache = SimpleTTLCache()
fan_cycle_service = FanCycleExperimentService(cache=cache)
yolo_demo_service = YoloDemoService()


@router.get("/fan-cycle/latest", response_model=FanCycleLatestResponse)
def get_latest_fan_cycle_run() -> FanCycleLatestResponse:
    try:
        return fan_cycle_service.get_latest()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/fan-cycle/live", response_model=FanCycleLiveResponse)
def get_live_fan_cycle_metrics() -> FanCycleLiveResponse:
    try:
        return fan_cycle_service.get_live()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/yolo-demo/status", response_model=YoloDemoStatusResponse)
def get_yolo_demo_status() -> YoloDemoStatusResponse:
    return yolo_demo_service.get_status()


@router.get("/yolo-demo/events", response_model=YoloDemoEventsResponse)
def get_yolo_demo_events() -> YoloDemoEventsResponse:
    return yolo_demo_service.get_events()


@router.post("/yolo-demo/start", response_model=YoloDemoStatusResponse)
def start_yolo_demo() -> YoloDemoStatusResponse:
    try:
        return yolo_demo_service.start()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/yolo-demo/stop", response_model=YoloDemoStatusResponse)
def stop_yolo_demo() -> YoloDemoStatusResponse:
    try:
        return yolo_demo_service.stop()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/yolo-demo/fan-mode/{mode}", response_model=YoloDemoStatusResponse)
def set_yolo_demo_fan_mode(mode: str) -> YoloDemoStatusResponse:
    try:
        return yolo_demo_service.apply_fan_mode(mode)  # type: ignore[arg-type]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
