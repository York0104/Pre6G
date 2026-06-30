import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import llm_lab as llm_lab_router
from app.schemas.llm_lab import LlmBenchmarkRunRequest, LlmInferenceRequest, LlmSmokeBenchmarkRequest
from app.services.llm_lab_service import LlmInferenceError


class LlmLabRouterTests(unittest.TestCase):
    def test_run_inference_route_returns_payload(self) -> None:
        payload = {
            "schema": "pre6g.llm_inference.v1",
            "ts": 1710000001,
            "namespace": "ai-serving",
            "workload": "gemma4-e2b-vllm",
            "target_service": "ai-serving/gemma4-e2b-vllm",
            "model": "gemma4-e2b-w4a16",
            "http_status": 200,
            "latency_seconds": 0.503,
            "prompt_tokens": 25,
            "completion_tokens": 128,
            "total_tokens": 153,
            "finish_reason": "length",
            "response_text": "ok",
        }
        request = LlmInferenceRequest(
            namespace="ai-serving",
            workload="gemma4-e2b-vllm",
            prompt="hello",
            max_tokens=128,
            temperature=0.0,
        )

        with patch.object(llm_lab_router.llm_lab_service, "run_inference", return_value=payload):
            response = llm_lab_router.run_inference(request)
        self.assertEqual(response.http_status, 200)
        self.assertEqual(response.total_tokens, 153)

    def test_run_inference_route_maps_service_error(self) -> None:
        request = LlmInferenceRequest(
            namespace="ai-serving",
            workload="gemma4-e2b-vllm",
            prompt="hello",
            max_tokens=128,
            temperature=0.0,
        )
        with patch.object(
            llm_lab_router.llm_lab_service,
            "run_inference",
            side_effect=LlmInferenceError(409, "workload is not ready"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                llm_lab_router.run_inference(request)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_run_smoke_benchmark_route_returns_payload(self) -> None:
        payload = {
            "schema": "pre6g.llm_smoke_benchmark.v1",
            "ts": 1710000001,
            "run_id": "smoke-20260627T073223Z",
            "namespace": "ai-serving",
            "workload": "gemma4-e2b-vllm",
            "profile": "Smoke",
            "request_count": 20,
            "max_tokens": 64,
            "temperature": 0.0,
            "status": "succeeded",
            "completed_requests": 20,
            "failed_requests": 0,
            "run_elapsed_seconds": 8.4,
            "request_throughput_rps": 2.381,
            "aggregate_prompt_tps": 47.619,
            "aggregate_generation_tps": 152.381,
            "aggregate_total_tps": 200.0,
            "latency_p50_seconds": 0.41,
            "latency_p95_seconds": 0.44,
            "mean_latency_seconds": 0.42,
            "mean_prompt_tokens": 20.0,
            "mean_completion_tokens": 64.0,
            "mean_total_tokens": 84.0,
        }
        request = LlmSmokeBenchmarkRequest(namespace="ai-serving", workload="gemma4-e2b-vllm")
        with patch.object(llm_lab_router.llm_lab_service, "run_smoke_benchmark", return_value=payload):
            response = llm_lab_router.run_smoke_benchmark(request)
        self.assertEqual(response.status, "succeeded")
        self.assertEqual(response.completed_requests, 20)

    def test_get_run_history_route_returns_payload(self) -> None:
        payload = {
            "schema": "pre6g.llm_run_history.v1",
            "ts": 1710000003,
            "count": 1,
            "items": [
                {
                    "ts": 1710000002,
                    "event_type": "controlled_batch",
                    "namespace": "ai-serving",
                    "workload": "gemma4-e2b-vllm",
                    "status": "succeeded",
                    "run_id": "smoke-20260627T073638Z",
                }
            ],
        }
        with patch.object(llm_lab_router.llm_lab_service, "get_history", return_value=payload):
            response = llm_lab_router.get_run_history(
                namespace="ai-serving",
                workload="gemma4-e2b-vllm",
                limit=20,
            )
        self.assertEqual(response.count, 1)
        self.assertEqual(response.items[0].event_type, "controlled_batch")

    def test_start_benchmark_run_route_returns_payload(self) -> None:
        payload = {
            "schema": "pre6g.llm_benchmark_run_start.v1",
            "ts": 1710000010,
            "run_id": "smoke-run-20260630T031500Z",
            "namespace": "ai-serving",
            "workload": "gemma4-e2b-vllm",
            "profile": "Smoke",
            "profile_id": "smoke",
            "status": "queued",
        }
        with patch.object(llm_lab_router.llm_lab_service, "start_benchmark_run", return_value=payload):
            response = llm_lab_router.start_benchmark_run(
                LlmBenchmarkRunRequest(
                    namespace="ai-serving",
                    workload="gemma4-e2b-vllm",
                    profile_id="smoke",
                )
            )
        self.assertEqual(response.run_id, payload["run_id"])

    def test_get_benchmark_run_route_returns_payload(self) -> None:
        payload = {
            "schema": "pre6g.llm_benchmark_run.v1",
            "ts": 1710000011,
            "run_id": "smoke-run-20260630T031500Z",
            "namespace": "ai-serving",
            "workload": "gemma4-e2b-vllm",
            "profile": "Smoke",
            "profile_id": "smoke",
            "status": "running",
            "request_count": 20,
            "concurrency": 1,
            "max_tokens": 64,
            "temperature": 0.0,
            "started_ts": 1710000010,
            "finished_ts": None,
            "progress": {
                "elapsed_seconds": 1.2,
                "completed_requests": 3,
                "failed_requests": 0,
                "prompt_tokens_so_far": 60.0,
                "completion_tokens_so_far": 192.0,
                "total_tokens_so_far": 252.0,
                "current_request_throughput_rps": 3.0,
                "current_prompt_tps": 60.0,
                "current_generation_tps": 192.0,
                "current_total_tps": 252.0,
                "buckets": [],
            },
            "result": None,
            "error": None,
        }
        with patch.object(llm_lab_router.llm_lab_service, "get_benchmark_run", return_value=payload):
            response = llm_lab_router.get_benchmark_run(payload["run_id"])
        self.assertEqual(response.status, "running")
        self.assertEqual(response.progress.completed_requests, 3)

    def test_cancel_benchmark_run_route_returns_payload(self) -> None:
        payload = {
            "schema": "pre6g.llm_benchmark_run_cancel.v1",
            "ts": 1710000012,
            "run_id": "smoke-run-20260630T031500Z",
            "status": "cancelling",
        }
        with patch.object(llm_lab_router.llm_lab_service, "cancel_benchmark_run", return_value=payload):
            response = llm_lab_router.cancel_benchmark_run(payload["run_id"])
        self.assertEqual(response.status, "cancelling")


if __name__ == "__main__":
    unittest.main()
