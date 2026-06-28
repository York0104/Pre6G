from fastapi import APIRouter, HTTPException

from app.schemas.llm_lab import (
    LlmInferenceRequest,
    LlmInferenceResponse,
    LlmSmokeBenchmarkRequest,
    LlmSmokeBenchmarkResponse,
)
from app.services.llm_lab_service import LlmInferenceError, LlmLabService

router = APIRouter(prefix="/api/v1/llm-lab", tags=["llm-lab"])

llm_lab_service = LlmLabService()


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
