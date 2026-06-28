import unittest
from unittest.mock import patch

import requests

from app.schemas.workload import (
    WorkloadAggregateMetrics,
    WorkloadIdentity,
    WorkloadReplicaStatus,
    WorkloadReplicaSummary,
    WorkloadStatusResponse,
)
from app.services.llm_lab_service import LlmInferenceError, LlmLabService


class FakeK8sAdapter:
    def get_service_raw(self, namespace: str, name: str):
        return {
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "clusterIP": "10.43.227.115",
                "ports": [{"port": 8000}],
            },
        }

    def list_services_raw(self, namespace: str | None = None):
        return []


class FakeWorkloadStatusService:
    def __init__(self, ready: int = 1):
        self.ready = ready

    def get_workload_status(self, namespace: str, workload: str):
        return WorkloadStatusResponse(
            schema="pre6g.workload_status.v1",
            ts=1710000001,
            freshness_seconds=0.2,
            query_window_seconds=10,
            metrics_observed_ts=1710000001,
            scrape_source="vmagent -> VictoriaMetrics",
            status="ready" if self.ready > 0 else "not_ready",
            identity=WorkloadIdentity(
                namespace=namespace,
                workload=workload,
                runtime="vllm",
                model_name="gemma4-e2b-w4a16",
                served_model_id="gemma4-e2b-w4a16",
                runtime_image="vllm/vllm-openai:v0.23.0",
                runtime_version="v0.23.0",
            ),
            replica_summary=WorkloadReplicaSummary(
                desired=1,
                ready=self.ready,
                metrics_available=self.ready,
                metrics_unavailable=0,
            ),
            replicas=[
                WorkloadReplicaStatus(
                    pod="gemma4-pod",
                    node_name="iccl-s3-251230",
                    status="ready",
                    owner_resolution="deployment",
                    pod_phase="Running",
                    ready_condition=self.ready > 0,
                    metrics_observed_ts=1710000001,
                    metrics_freshness_seconds=0.2,
                    generation_tokens_per_second=0.0,
                    prompt_tokens_per_second=0.0,
                    waiting_requests=0.0,
                    kv_cache_usage_percent=0.0,
                )
            ],
            aggregate=WorkloadAggregateMetrics(
                generation_tokens_per_second=0.0,
                prompt_tokens_per_second=0.0,
                waiting_requests=0.0,
                kv_cache_usage_percent_max=0.0,
            ),
        )


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class LlmLabServiceTests(unittest.TestCase):
    def test_run_inference_returns_usage_and_text(self) -> None:
        service = LlmLabService(
            workload_status_service=FakeWorkloadStatusService(),
            k8s_adapter=FakeK8sAdapter(),
        )

        with patch("app.services.llm_lab_service.requests.post") as post:
            post.return_value = FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": "hello from gemma"},
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 18,
                        "total_tokens": 30,
                    },
                },
            )
            response = service.run_inference(
                namespace="ai-serving",
                workload="gemma4-e2b-vllm",
                prompt="hello",
                max_tokens=64,
                temperature=0.0,
            )

        self.assertEqual(response["http_status"], 200)
        self.assertEqual(response["model"], "gemma4-e2b-w4a16")
        self.assertEqual(response["prompt_tokens"], 12)
        self.assertEqual(response["completion_tokens"], 18)
        self.assertEqual(response["total_tokens"], 30)
        self.assertEqual(response["finish_reason"], "stop")
        self.assertEqual(response["response_text"], "hello from gemma")

    def test_run_inference_rejects_not_ready_workload(self) -> None:
        service = LlmLabService(
            workload_status_service=FakeWorkloadStatusService(ready=0),
            k8s_adapter=FakeK8sAdapter(),
        )
        with self.assertRaises(LlmInferenceError) as ctx:
            service.run_inference(
                namespace="ai-serving",
                workload="gemma4-e2b-vllm",
                prompt="hello",
                max_tokens=64,
                temperature=0.0,
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_run_inference_maps_timeout_to_504(self) -> None:
        service = LlmLabService(
            workload_status_service=FakeWorkloadStatusService(),
            k8s_adapter=FakeK8sAdapter(),
        )
        with patch("app.services.llm_lab_service.requests.post", side_effect=requests.Timeout()):
            with self.assertRaises(LlmInferenceError) as ctx:
                service.run_inference(
                    namespace="ai-serving",
                    workload="gemma4-e2b-vllm",
                    prompt="hello",
                    max_tokens=64,
                    temperature=0.0,
                )
        self.assertEqual(ctx.exception.status_code, 504)

    def test_run_smoke_benchmark_aggregates_summary(self) -> None:
        service = LlmLabService(
            workload_status_service=FakeWorkloadStatusService(),
            k8s_adapter=FakeK8sAdapter(),
        )
        with patch.object(
            service,
            "run_inference",
            return_value={
                "latency_seconds": 0.4,
                "prompt_tokens": 20,
                "completion_tokens": 64,
                "total_tokens": 84,
            },
        ):
            response = service.run_smoke_benchmark(
                namespace="ai-serving",
                workload="gemma4-e2b-vllm",
            )
        self.assertEqual(response["status"], "succeeded")
        self.assertEqual(response["completed_requests"], 20)
        self.assertEqual(response["failed_requests"], 0)
        self.assertEqual(response["mean_latency_seconds"], 0.4)
        self.assertEqual(response["mean_prompt_tokens"], 20.0)
        self.assertEqual(response["mean_completion_tokens"], 64.0)

    def test_run_smoke_benchmark_all_failures_raise_first_error(self) -> None:
        service = LlmLabService(
            workload_status_service=FakeWorkloadStatusService(),
            k8s_adapter=FakeK8sAdapter(),
        )
        with patch.object(
            service,
            "run_inference",
            side_effect=LlmInferenceError(502, "failed to reach vLLM"),
        ):
            with self.assertRaises(LlmInferenceError) as ctx:
                service.run_smoke_benchmark(
                    namespace="ai-serving",
                    workload="gemma4-e2b-vllm",
                )
        self.assertEqual(ctx.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
