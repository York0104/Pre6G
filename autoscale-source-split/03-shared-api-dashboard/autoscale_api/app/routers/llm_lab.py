from fastapi import APIRouter, HTTPException, Query

from app.schemas.llm_lab import (
    LlmBenchmarkRequest,
    LlmBenchmarkRunCancelResponse,
    LlmBenchmarkRunRequest,
    LlmBenchmarkRunStartResponse,
    LlmBenchmarkRunStatusResponse,
    LlmBenchmarkResponse,
    LlmInferenceRequest,
    LlmInferenceResponse,
    LlmOfflineThroughputRequest,
    LlmRunHistoryResponse,
    LlmSmokeBenchmarkRequest,
    LlmSmokeBenchmarkResponse,
    LlamacppOfflineBenchmarkProfilesResponse,
    LlamacppOfflineBenchmarkRunCancelResponse,
    LlamacppOfflineBenchmarkRunRequest,
    LlamacppOfflineBenchmarkRunStartResponse,
    LlamacppOfflineBenchmarkRunStateResponse,
    LlamacppOfflineBenchmarkRunsResponse,
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


@router.post("/benchmarks/runs", response_model=LlmBenchmarkRunStartResponse)
def start_benchmark_run(request: LlmBenchmarkRunRequest) -> LlmBenchmarkRunStartResponse:
    try:
        payload = llm_lab_service.start_benchmark_run(
            namespace=request.namespace,
            workload=request.workload,
            profile=request.profile_id,
        )
        return LlmBenchmarkRunStartResponse(**payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LlmInferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/benchmarks/runs/{run_id}", response_model=LlmBenchmarkRunStatusResponse)
def get_benchmark_run(run_id: str) -> LlmBenchmarkRunStatusResponse:
    try:
        payload = llm_lab_service.get_benchmark_run(run_id=run_id)
        return LlmBenchmarkRunStatusResponse(**payload)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown benchmark run: {run_id}")


@router.post("/benchmarks/runs/{run_id}/cancel", response_model=LlmBenchmarkRunCancelResponse)
def cancel_benchmark_run(run_id: str) -> LlmBenchmarkRunCancelResponse:
    try:
        payload = llm_lab_service.cancel_benchmark_run(run_id=run_id)
        return LlmBenchmarkRunCancelResponse(**payload)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown benchmark run: {run_id}")


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


@router.post("/offline-throughput", response_model=LlmBenchmarkResponse)
def run_offline_throughput(request: LlmOfflineThroughputRequest) -> LlmBenchmarkResponse:
    try:
        payload = llm_lab_service.run_offline_throughput_profile(
            namespace=request.namespace,
            workload=request.workload,
            profile=request.profile_id,
        )
        return LlmBenchmarkResponse(**payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LlmInferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get(
    "/llamacpp/offline-benchmark/profiles",
    response_model=LlamacppOfflineBenchmarkProfilesResponse,
)
def get_llamacpp_offline_profiles() -> LlamacppOfflineBenchmarkProfilesResponse:
    payload = llm_lab_service.get_llamacpp_offline_profiles()
    return LlamacppOfflineBenchmarkProfilesResponse(**payload)


@router.post(
    "/llamacpp/offline-benchmark/runs",
    response_model=LlamacppOfflineBenchmarkRunStartResponse,
)
def start_llamacpp_offline_run(
    request: LlamacppOfflineBenchmarkRunRequest,
) -> LlamacppOfflineBenchmarkRunStartResponse:
    try:
        payload = llm_lab_service.start_llamacpp_offline_run(profile=request.profile)
        return LlamacppOfflineBenchmarkRunStartResponse(**payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LlmInferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get(
    "/llamacpp/offline-benchmark/runs/latest",
    response_model=LlamacppOfflineBenchmarkRunStateResponse,
)
def get_llamacpp_offline_latest_run() -> LlamacppOfflineBenchmarkRunStateResponse:
    try:
        payload = llm_lab_service.get_llamacpp_offline_latest_run()
        return LlamacppOfflineBenchmarkRunStateResponse(**payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="no llama.cpp offline benchmark run found")


@router.get(
    "/llamacpp/offline-benchmark/runs/{run_id}",
    response_model=LlamacppOfflineBenchmarkRunStateResponse,
)
def get_llamacpp_offline_run(run_id: str) -> LlamacppOfflineBenchmarkRunStateResponse:
    try:
        payload = llm_lab_service.get_llamacpp_offline_run(run_id=run_id)
        return LlamacppOfflineBenchmarkRunStateResponse(**payload)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown llama.cpp offline benchmark run: {run_id}")


@router.post(
    "/llamacpp/offline-benchmark/runs/{run_id}/cancel",
    response_model=LlamacppOfflineBenchmarkRunCancelResponse,
)
def cancel_llamacpp_offline_run(run_id: str) -> LlamacppOfflineBenchmarkRunCancelResponse:
    try:
        payload = llm_lab_service.cancel_llamacpp_offline_run(run_id=run_id)
        return LlamacppOfflineBenchmarkRunCancelResponse(**payload)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown llama.cpp offline benchmark run: {run_id}")


@router.get(
    "/llamacpp/offline-benchmark/runs",
    response_model=LlamacppOfflineBenchmarkRunsResponse,
)
def list_llamacpp_offline_runs(
    limit: int = Query(default=10, ge=1, le=50),
) -> LlamacppOfflineBenchmarkRunsResponse:
    payload = llm_lab_service.list_llamacpp_offline_runs(limit=limit)
    return LlamacppOfflineBenchmarkRunsResponse(**payload)
