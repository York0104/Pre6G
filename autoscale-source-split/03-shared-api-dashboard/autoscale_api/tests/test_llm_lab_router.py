import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import llm_lab as llm_lab_router
from app.schemas.llm_lab import LlmInferenceRequest, LlmSmokeBenchmarkRequest
from app.services.llm_lab_service import LlmInferenceError


class LlmLabRouterTests(unittest.TestCase):
    def test_run_inference_route_returns_payload(self) -> None:
        payload = {
            "schema": "pre6g.llm_inference.v1",
            "ts": 1710000001,
            "namespace": "ai-serving",
            "workload": "gemma4-e2b-vllm",
            "target_url": "http://10.43.227.115:8000/v1/chat/completions",
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


if __name__ == "__main__":
    unittest.main()
