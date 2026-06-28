from fastapi import APIRouter, HTTPException, Query

from app.schemas.llm_lab import (
    LlmBenchmarkRequest,
    LlmBenchmarkResponse,
    LlmInferenceRequest,
    LlmInferenceResponse,
    LlmRunHistoryResponse,
    LlmSmokeBenchmarkRequest,
    LlmSmokeBenchmarkResponse,
)
from app.services.llm_lab_service import LlmInferenceError, LlmLabService

router = APIRouter(prefix="/api/v1/llm-lab", tags=["llm-lab"])

llm_lab_service = LlmLabService()


@router.get("/history", response_model=LlmRunHistoryResponse)
def get_run_history(
    namespace: str | None = Query(default=None),
    workload: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> LlmRunHistoryResponse:
    payload = llm_lab_service.get_history(namespace=namespace, workload=workload, limit=limit)
    return LlmRunHistoryResponse(**payload)


@router.post("/inference", response_model=LlmInferenceResponse)
def run_inference(request: LlmInferenceRequest) -> LlmInferenceResponse:
    try:
        payload = llm_lab_service.run_inference(
            namespace=request.namespace,
            workload=request.workload,
            prompt=request.prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        return LlmInferenceResponse(**payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LlmInferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/benchmarks/smoke", response_model=LlmSmokeBenchmarkResponse)
def run_smoke_benchmark(request: LlmSmokeBenchmarkRequest) -> LlmSmokeBenchmarkResponse:
    try:
        payload = llm_lab_service.run_smoke_benchmark(
            namespace=request.namespace,
            workload=request.workload,
        )
        return LlmSmokeBenchmarkResponse(**payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LlmInferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/benchmarks/{profile}", response_model=LlmBenchmarkResponse)
def run_benchmark_profile(profile: str, request: LlmBenchmarkRequest) -> LlmBenchmarkResponse:
    try:
        payload = llm_lab_service.run_benchmark_profile(
            namespace=request.namespace,
            workload=request.workload,
            profile=profile,
        )
        return LlmBenchmarkResponse(**payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LlmInferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
