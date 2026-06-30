import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import threading
import time

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
    def _make_service(self, ready: int = 1) -> LlmLabService:
        service = LlmLabService(
            workload_status_service=FakeWorkloadStatusService(ready=ready),
            k8s_adapter=FakeK8sAdapter(),
        )
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        service.history_path = Path(tempdir.name) / "history.jsonl"
        return service

    def test_run_inference_returns_usage_and_text(self) -> None:
        service = self._make_service()

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
        service = self._make_service(ready=0)
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
        service = self._make_service()
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
        service = self._make_service()
        with patch.object(
            service,
            "_resolve_ready_target",
            return_value=("http://10.43.227.115:8000/v1/chat/completions", "gemma4-e2b-w4a16"),
        ), patch.object(
            service,
            "_execute_inference_request",
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
        self.assertGreater(response["run_elapsed_seconds"], 0)
        self.assertGreater(response["request_throughput_rps"], 0)
        self.assertEqual(response["aggregate_prompt_tps"] > 0, True)
        self.assertEqual(response["aggregate_generation_tps"] > 0, True)
        self.assertEqual(response["aggregate_total_tps"] > 0, True)
        self.assertEqual(response["latency_p50_seconds"], 0.4)
        self.assertEqual(response["latency_p95_seconds"], 0.4)

    def test_run_smoke_benchmark_all_failures_raise_first_error(self) -> None:
        service = self._make_service()
        with patch.object(
            service,
            "_resolve_ready_target",
            return_value=("http://10.43.227.115:8000/v1/chat/completions", "gemma4-e2b-w4a16"),
        ), patch.object(
            service,
            "_execute_inference_request",
            side_effect=LlmInferenceError(502, "failed to reach vLLM"),
        ):
            with self.assertRaises(LlmInferenceError) as ctx:
                service.run_smoke_benchmark(
                    namespace="ai-serving",
                    workload="gemma4-e2b-vllm",
                )
        self.assertEqual(ctx.exception.status_code, 502)

    def test_run_benchmark_profile_uses_real_concurrency(self) -> None:
        service = self._make_service()
        profile_id = "test-concurrent"
        service.BENCHMARK_PROFILES[profile_id] = {
            "display_name": "Test Concurrent",
            "prompt": "hello",
            "max_tokens": 16,
            "temperature": 0.0,
            "concurrency": 3,
            "request_count": 6,
            "description": "test profile",
        }

        lock = threading.Lock()
        active = 0
        max_active = 0

        def fake_execute_inference_request(**_: object) -> dict[str, object]:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return {
                "http_status": 200,
                "latency_seconds": 0.03,
                "prompt_tokens": 10,
                "completion_tokens": 16,
                "total_tokens": 26,
                "finish_reason": "stop",
                "response_text": "ok",
            }

        try:
            with patch.object(
                service,
                "_resolve_ready_target",
                return_value=("http://10.43.227.115:8000/v1/chat/completions", "gemma4-e2b-w4a16"),
            ), patch.object(
                service,
                "_execute_inference_request",
                side_effect=fake_execute_inference_request,
            ):
                response = service.run_benchmark_profile(
                    namespace="ai-serving",
                    workload="gemma4-e2b-vllm",
                    profile=profile_id,
                )
        finally:
            del service.BENCHMARK_PROFILES[profile_id]

        self.assertEqual(response["completed_requests"], 6)
        self.assertEqual(response["failed_requests"], 0)
        self.assertEqual(response["concurrency"], 3)
        self.assertGreaterEqual(max_active, 2)

    def test_get_history_returns_recent_items(self) -> None:
        service = self._make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            service.history_path = Path(tmpdir) / "history.jsonl"
            service._append_history(
                {
                    "ts": 1710000001,
                    "event_type": "single_inference",
                    "namespace": "ai-serving",
                    "workload": "gemma4-e2b-vllm",
                    "status": "succeeded",
                }
            )
            service._append_history(
                {
                    "ts": 1710000002,
                    "event_type": "controlled_batch",
                    "namespace": "ai-serving",
                    "workload": "gemma4-e2b-vllm",
                    "status": "succeeded",
                }
            )
            history = service.get_history(namespace="ai-serving", workload="gemma4-e2b-vllm", limit=10)
        self.assertEqual(history["count"], 2)
        self.assertEqual(history["items"][0]["event_type"], "controlled_batch")

    def test_start_benchmark_run_exposes_progress_and_result(self) -> None:
        service = self._make_service()
        with patch.object(
            service,
            "_resolve_ready_target",
            return_value=("http://10.43.227.115:8000/v1/chat/completions", "gemma4-e2b-w4a16"),
        ), patch.object(
            service,
            "_execute_inference_request",
            return_value={
                "http_status": 200,
                "latency_seconds": 0.01,
                "prompt_tokens": 10,
                "completion_tokens": 16,
                "total_tokens": 26,
                "finish_reason": "stop",
                "response_text": "ok",
            },
        ):
            started = service.start_benchmark_run(
                namespace="ai-serving",
                workload="gemma4-e2b-vllm",
                profile="smoke",
            )
            run_id = started["run_id"]
            deadline = time.time() + 2.0
            snapshot = service.get_benchmark_run(run_id=run_id)
            while snapshot["status"] in {"queued", "running", "cancelling"} and time.time() < deadline:
                time.sleep(0.05)
                snapshot = service.get_benchmark_run(run_id=run_id)

        self.assertEqual(snapshot["run_id"], run_id)
        self.assertIn(snapshot["status"], {"succeeded", "completed_with_errors"})
        self.assertIsNotNone(snapshot["result"])
        self.assertGreaterEqual(snapshot["progress"]["completed_requests"], 1)

    def test_cancel_benchmark_run_marks_cancelling(self) -> None:
        service = self._make_service()
        run_id = "manual-run"
        state = service._build_run_state(
            run_id=run_id,
            namespace="ai-serving",
            workload="gemma4-e2b-vllm",
            profile_id="smoke",
            profile_config=service.BENCHMARK_PROFILES["smoke"],
        )
        service._write_run_state(run_id, state)
        cancel_event = threading.Event()
        with service._run_state_lock:
            service._active_run_controls[run_id] = cancel_event
        response = service.cancel_benchmark_run(run_id=run_id)
        self.assertEqual(response["status"], "cancelling")
        self.assertTrue(cancel_event.is_set())

    def test_update_run_progress_fills_missing_seconds_with_zero_buckets(self) -> None:
        service = self._make_service()
        state = {
            "progress": service._initial_progress_state(),
        }
        base = time.time()
        service._update_run_progress(
            state=state,
            started_monotonic=base,
            completed_delta=1,
            prompt_tokens_delta=10.0,
            completion_tokens_delta=16.0,
            total_tokens_delta=26.0,
        )
        service._refresh_run_progress_clock(
            state=state,
            started_monotonic=time.time() - 3.2,
        )
        buckets = state["progress"]["buckets"]
        self.assertGreaterEqual(len(buckets), 4)
        seconds = [bucket["second"] for bucket in buckets]
        self.assertEqual(seconds, list(range(seconds[0], seconds[-1] + 1)))
        zero_buckets = [bucket for bucket in buckets[:-1] if bucket["total_tokens"] == 0.0]
        self.assertTrue(len(zero_buckets) >= 1)


if __name__ == "__main__":
    unittest.main()
