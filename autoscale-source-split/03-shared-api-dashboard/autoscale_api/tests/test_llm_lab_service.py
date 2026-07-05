import tempfile
import threading
import time
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch

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
            query_window_seconds=3,
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
                    generation_tokens_per_second=32.0,
                    prompt_tokens_per_second=8.0,
                    waiting_requests=0.0,
                    kv_cache_usage_percent=0.0,
                )
            ],
            aggregate=WorkloadAggregateMetrics(
                generation_tokens_per_second=32.0,
                prompt_tokens_per_second=8.0,
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
        service.runs_root = Path(tempdir.name) / "runs"
        service.runs_root.mkdir(parents=True, exist_ok=True)
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
        with patch.object(service, "_build_benchmark_exec_command", return_value=["kubectl", "exec", "fake"]), patch.object(
            service,
            "_read_benchmark_result_payload",
            return_value={
                "duration": 8.4,
                "completed": 20,
                "failed": 0,
                "total_input_tokens": 400,
                "total_output_tokens": 1280,
                "request_throughput": 2.381,
                "output_throughput": 152.381,
                "total_token_throughput": 200.0,
                "median_e2el_ms": 410,
                "p95_e2el_ms": 440,
                "mean_e2el_ms": 420,
                "mean_ttft_ms": 150,
                "p95_ttft_ms": 190,
                "mean_tpot_ms": 12,
                "p95_tpot_ms": 20,
                "mean_itl_ms": 8,
                "p95_itl_ms": 12,
            },
        ), patch("app.services.llm_lab_service.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
            response = service.run_smoke_benchmark(
                namespace="ai-serving",
                workload="gemma4-e2b-vllm",
            )

        self.assertEqual(response["status"], "succeeded")
        self.assertEqual(response["completed_requests"], 20)
        self.assertEqual(response["failed_requests"], 0)
        self.assertEqual(response["mean_latency_seconds"], 0.42)
        self.assertEqual(response["mean_prompt_tokens"], 20.0)
        self.assertEqual(response["mean_completion_tokens"], 64.0)
        self.assertEqual(response["request_throughput_rps"], 2.381)
        self.assertEqual(response["aggregate_prompt_tps"], 47.619)
        self.assertEqual(response["aggregate_generation_tps"], 152.381)
        self.assertEqual(response["aggregate_total_tps"], 200.0)
        self.assertEqual(response["latency_p50_seconds"], 0.41)
        self.assertEqual(response["latency_p95_seconds"], 0.44)
        self.assertEqual(response["mean_ttft_seconds"], 0.15)
        self.assertEqual(response["p95_ttft_seconds"], 0.19)

    def test_run_smoke_benchmark_failure_maps_subprocess_error(self) -> None:
        service = self._make_service()
        with patch.object(service, "_build_benchmark_exec_command", return_value=["kubectl", "exec", "fake"]), patch(
            "app.services.llm_lab_service.subprocess.run"
        ) as mock_run:
            mock_run.return_value = Mock(returncode=2, stdout="", stderr="bench failed")
            with self.assertRaises(LlmInferenceError) as ctx:
                service.run_smoke_benchmark(
                    namespace="ai-serving",
                    workload="gemma4-e2b-vllm",
                )
        self.assertEqual(ctx.exception.status_code, 502)

    def test_run_benchmark_profile_uses_vllm_bench_payload_mapping(self) -> None:
        service = self._make_service()
        profile_id = "test-bench"
        service.BENCHMARK_PROFILES[profile_id] = {
            "display_name": "Test Bench",
            "model": "example/model",
            "served_model_name": "example-model",
            "input_len": 256,
            "max_tokens": 16,
            "temperature": 0.0,
            "concurrency": 3,
            "request_count": 6,
            "description": "test profile",
        }

        try:
            with patch.object(service, "_build_benchmark_exec_command", return_value=["kubectl", "exec", "fake"]), patch.object(
                service,
                "_read_benchmark_result_payload",
                return_value={
                    "duration": 4.0,
                    "completed": 6,
                    "failed": 1,
                    "total_input_tokens": 600,
                    "total_output_tokens": 96,
                    "request_throughput": 1.5,
                    "output_throughput": 24.0,
                    "total_token_throughput": 174.0,
                    "median_e2el_ms": 700,
                    "p95_e2el_ms": 990,
                    "mean_e2el_ms": 760,
                },
            ), patch("app.services.llm_lab_service.subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
                response = service.run_benchmark_profile(
                    namespace="ai-serving",
                    workload="gemma4-e2b-vllm",
                    profile=profile_id,
                )
        finally:
            del service.BENCHMARK_PROFILES[profile_id]

        self.assertEqual(response["completed_requests"], 6)
        self.assertEqual(response["failed_requests"], 1)
        self.assertEqual(response["concurrency"], 3)
        self.assertEqual(response["status"], "completed_with_errors")
        self.assertEqual(response["aggregate_prompt_tps"], 150.0)

    def test_run_offline_throughput_requires_dedicated_target_configuration(self) -> None:
        service = self._make_service()
        with self.assertRaises(LlmInferenceError) as ctx:
            service.run_offline_throughput_profile(
                namespace="ai-serving",
                workload="gemma4-e2b-vllm",
                profile="smoke",
            )
        self.assertEqual(ctx.exception.status_code, 409)

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
                    "event_type": "serving_benchmark",
                    "namespace": "ai-serving",
                    "workload": "gemma4-e2b-vllm",
                    "status": "succeeded",
                }
            )
            history = service.get_history(namespace="ai-serving", workload="gemma4-e2b-vllm", limit=10)
        self.assertEqual(history["count"], 2)
        self.assertEqual(history["items"][0]["event_type"], "serving_benchmark")

    def test_start_benchmark_run_exposes_progress_and_result(self) -> None:
        service = self._make_service()
        mock_process = Mock()
        mock_process.poll.side_effect = [None, 0, 0, 0, 0]
        mock_process.returncode = 0
        mock_process.stderr = None
        with patch.object(
            service,
            "_resolve_ready_target",
            return_value=("http://10.43.227.115:8000/v1/chat/completions", "gemma4-e2b-w4a16"),
        ), patch("app.services.llm_lab_service.subprocess.Popen", return_value=mock_process), patch.object(
            service,
            "_read_benchmark_result_payload",
            return_value={
                "duration": 1.2,
                "completed": 20,
                "failed": 0,
                "total_input_tokens": 400,
                "total_output_tokens": 1280,
                "request_throughput": 16.7,
                "output_throughput": 1066.7,
                "total_token_throughput": 1400.0,
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
        self.assertGreaterEqual(snapshot["progress"]["prompt_tokens_so_far"], 400.0)

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
        mock_process = Mock()
        mock_process.poll.return_value = None
        with service._run_state_lock:
            service._active_run_controls[run_id] = {"cancel_event": cancel_event, "process": mock_process}
        response = service.cancel_benchmark_run(run_id=run_id)
        self.assertEqual(response["status"], "cancelling")
        self.assertTrue(cancel_event.is_set())
        mock_process.terminate.assert_called_once()

    def test_start_continuous_benchmark_run_can_stop_and_returns_summary(self) -> None:
        service = self._make_service()
        mock_process = Mock()
        poll_calls = {"count": 0}

        def fake_poll():
            poll_calls["count"] += 1
            return None if poll_calls["count"] == 1 else 0

        mock_process.poll.side_effect = fake_poll
        mock_process.returncode = 0
        mock_process.stderr = None
        with patch.object(
            service,
            "_resolve_ready_target",
            return_value=("http://10.43.227.115:8000/v1/chat/completions", "gemma4-e2b-w4a16"),
        ), patch("app.services.llm_lab_service.subprocess.Popen", return_value=mock_process), patch.object(
            service,
            "_read_benchmark_result_payload",
            return_value={
                "duration": 1.0,
                "completed": 20,
                "failed": 0,
                "total_input_tokens": 400,
                "total_output_tokens": 1280,
                "mean_e2el_ms": 250,
                "mean_ttft_ms": 10,
                "mean_tpot_ms": 3.5,
                "mean_itl_ms": 3.4,
            },
        ):
            started = service.start_benchmark_run(
                namespace="ai-serving",
                workload="gemma4-e2b-vllm",
                profile="continuous",
            )
            run_id = started["run_id"]
            time.sleep(0.1)
            service.cancel_benchmark_run(run_id=run_id)
            deadline = time.time() + 2.0
            snapshot = service.get_benchmark_run(run_id=run_id)
            while snapshot["status"] in {"queued", "running", "cancelling"} and time.time() < deadline:
                time.sleep(0.05)
                snapshot = service.get_benchmark_run(run_id=run_id)

        self.assertEqual(snapshot["run_id"], run_id)
        self.assertEqual(snapshot["status"], "cancelled")
        self.assertIsNotNone(snapshot["result"])
        self.assertGreaterEqual(snapshot["result"]["completed_requests"], 0)

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

    def test_parse_llamacpp_benchmark_payload_maps_pp_tg_pg(self) -> None:
        service = self._make_service()
        fixture_path = Path(__file__).parent / "fixtures" / "llama_bench_pascal_output.json"
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        result = service._parse_llamacpp_benchmark_payload(payload)
        self.assertEqual(result["prompt_tps_mean"], 1188.432)
        self.assertEqual(result["generation_tps_mean"], 302.615)
        self.assertEqual(result["prompt_generation_tps_mean"], 254.881)
        self.assertEqual(result["n_prompt"], 512)
        self.assertEqual(result["n_gpu_layers"], -1)

    def test_parse_llamacpp_benchmark_payload_allows_missing_pg(self) -> None:
        service = self._make_service()
        payload = {
            "repetitions": 3,
            "results": [
                {"test": "pp", "avg_ts": 900.0, "stdev_ts": 10.0, "n_prompt": 128, "n_gen": 64},
                {"test": "tg", "avg_ts": 220.0, "stdev_ts": 4.0, "n_prompt": 128, "n_gen": 64},
            ],
        }
        result = service._parse_llamacpp_benchmark_payload(payload)
        self.assertEqual(result["prompt_generation_tps_mean"], None)
        self.assertEqual(result["prompt_generation_tps_stddev"], None)

    def test_parse_llamacpp_benchmark_payload_rejects_malformed_shape(self) -> None:
        service = self._make_service()
        with self.assertRaises(LlmInferenceError) as ctx:
            service._parse_llamacpp_benchmark_payload({"results": "nope"})
        self.assertEqual(ctx.exception.status_code, 502)

    def test_parse_gpu_preflight_output(self) -> None:
        service = self._make_service()
        output = "5791, python3, 402 MiB\n8123, another-proc, 128 MiB\n"
        processes = service._parse_gpu_preflight_output(output)
        self.assertEqual(len(processes), 2)
        self.assertEqual(processes[0]["pid"], 5791)
        self.assertEqual(processes[0]["used_memory"], "402 MiB")

    def test_start_llamacpp_offline_run_returns_latest_result(self) -> None:
        service = self._make_service()
        fixture_path = Path(__file__).parent / "fixtures" / "llama_bench_pascal_output.json"
        fixture_stdout = fixture_path.read_text(encoding="utf-8")
        with patch.object(
            service,
            "_run_llamacpp_gpu_preflight",
            return_value=[{"pid": 5791, "process_name": "python3", "used_memory": "402 MiB"}],
        ), patch("app.services.llm_lab_service.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=fixture_stdout, stderr="")
            started = service.start_llamacpp_offline_run(profile="pascal-throughput")
            run_id = started["run_id"]
            deadline = time.time() + 2.0
            snapshot = service.get_llamacpp_offline_run(run_id=run_id)
            while snapshot["status"] in {"queued", "running"} and time.time() < deadline:
                time.sleep(0.05)
                snapshot = service.get_llamacpp_offline_run(run_id=run_id)

        self.assertEqual(snapshot["status"], "succeeded")
        self.assertIsNotNone(snapshot["result"])
        self.assertTrue(snapshot["result"]["gpu_contended"])
        self.assertEqual(snapshot["result"]["prompt_tps_mean"], 1188.432)

    def test_start_llamacpp_offline_run_rejects_when_active_run_exists(self) -> None:
        service = self._make_service()
        with service._run_state_lock:
            service._active_run_controls["llamacpp-run-1"] = {"kind": "llamacpp_offline"}
        with self.assertRaises(LlmInferenceError) as ctx:
            service.start_llamacpp_offline_run(profile="pascal-smoke")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_llamacpp_offline_run_marks_failed_on_command_error(self) -> None:
        service = self._make_service()
        with patch.object(service, "_run_llamacpp_gpu_preflight", return_value=[]), patch(
            "app.services.llm_lab_service.subprocess.run"
        ) as mock_run:
            mock_run.return_value = Mock(returncode=2, stdout="", stderr="boom")
            started = service.start_llamacpp_offline_run(profile="pascal-smoke")
            run_id = started["run_id"]
            deadline = time.time() + 2.0
            snapshot = service.get_llamacpp_offline_run(run_id=run_id)
            while snapshot["status"] in {"queued", "running"} and time.time() < deadline:
                time.sleep(0.05)
                snapshot = service.get_llamacpp_offline_run(run_id=run_id)
        self.assertEqual(snapshot["status"], "failed")
        self.assertIn("llama-bench failed", snapshot["error"])


if __name__ == "__main__":
    unittest.main()
