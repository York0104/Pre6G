import os
import time
import json
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Optional

import requests

from app.adapters.k8s_adapter import K8sAdapter
from app.services.workload_status_service import WorkloadStatusService


class LlmInferenceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _BenchmarkProfile(dict):
    pass


class LlmLabService:
    BENCHMARK_PROFILES: dict[str, dict[str, Any]] = {
        "smoke": {
            "display_name": "Smoke",
            "model": "unsloth/gemma-4-E2B-it-qat-w4a16",
            "served_model_name": "gemma4-e2b-w4a16",
            "input_len": 128,
            "max_tokens": 64,
            "temperature": 0.0,
            "concurrency": 1,
            "request_count": 20,
            "description": "Minimal official vLLM serving benchmark for control-path and TPS visibility checks.",
        },
        "steady": {
            "display_name": "Steady",
            "model": "unsloth/gemma-4-E2B-it-qat-w4a16",
            "served_model_name": "gemma4-e2b-w4a16",
            "input_len": 512,
            "max_tokens": 128,
            "temperature": 0.0,
            "concurrency": 4,
            "request_count": 30,
            "description": "Official vLLM serving benchmark with sustained concurrent requests.",
        },
        "long-context": {
            "display_name": "Long Context",
            "model": "unsloth/gemma-4-E2B-it-qat-w4a16",
            "served_model_name": "gemma4-e2b-w4a16",
            "input_len": 4096,
            "max_tokens": 64,
            "temperature": 0.0,
            "concurrency": 2,
            "request_count": 8,
            "description": "Official vLLM serving benchmark with longer prompt context pressure.",
        },
        "continuous": {
            "display_name": "Continuous",
            "model": "unsloth/gemma-4-E2B-it-qat-w4a16",
            "served_model_name": "gemma4-e2b-w4a16",
            "input_len": 512,
            "max_tokens": 128,
            "temperature": 0.0,
            "concurrency": 8,
            "request_count": 50,
            "continuous": True,
            "max_runtime_seconds": 1800,
            "description": "Continuously repeats denser official vLLM serving benchmark chunks until stopped or the safety limit is reached.",
        },
    }
    OFFLINE_THROUGHPUT_PROFILES: dict[str, dict[str, Any]] = {
        "smoke": {
            "display_name": "Offline Smoke",
            "model": "Qwen/Qwen2.5-1.5B-Instruct",
            "served_model_name": "Qwen/Qwen2.5-1.5B-Instruct",
            "input_len": 128,
            "max_tokens": 64,
            "temperature": 0.0,
            "concurrency": 1,
            "request_count": 16,
            "gpu_memory_utilization": 0.72,
            "max_model_len": 2048,
            "description": "Small offline throughput smoke benchmark.",
        },
        "steady": {
            "display_name": "Offline Steady",
            "model": "Qwen/Qwen2.5-1.5B-Instruct",
            "served_model_name": "Qwen/Qwen2.5-1.5B-Instruct",
            "input_len": 384,
            "max_tokens": 128,
            "temperature": 0.0,
            "concurrency": 1,
            "request_count": 48,
            "gpu_memory_utilization": 0.72,
            "max_model_len": 2048,
            "description": "Offline throughput benchmark for hardware-oriented batch capacity checks.",
        },
    }

    def __init__(
        self,
        workload_status_service: WorkloadStatusService | None = None,
        k8s_adapter: K8sAdapter | None = None,
    ) -> None:
        self.workloads = workload_status_service or WorkloadStatusService()
        self.k8s = k8s_adapter or K8sAdapter()
        self.request_timeout_seconds = float(
            (os.getenv("PRE6G_LLM_INFERENCE_TIMEOUT_SECONDS", "120").strip() or "120")
        )
        runtime_root = Path(__file__).resolve().parents[1] / "runtime" / "llm_lab"
        runtime_root.mkdir(parents=True, exist_ok=True)
        self.history_path = runtime_root / "history.jsonl"
        self.runs_root = runtime_root / "runs"
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._run_state_lock = Lock()
        self._active_run_controls: dict[str, dict[str, Any]] = {}
        self.kubectl_bin = os.getenv("PRE6G_KUBECTL_BIN", "kubectl").strip() or "kubectl"
        self.benchmark_timeout_seconds = float(
            (os.getenv("PRE6G_LLM_BENCHMARK_TIMEOUT_SECONDS", "1800").strip() or "1800")
        )
        self.offline_bench_namespace = os.getenv("PRE6G_LLM_OFFLINE_BENCH_NAMESPACE", "").strip()
        self.offline_bench_target = os.getenv("PRE6G_LLM_OFFLINE_BENCH_TARGET", "").strip()

    @staticmethod
    def _selector_match(labels: dict[str, Any], selector: dict[str, Any]) -> bool:
        if not selector:
            return False
        for key, expected in selector.items():
            if labels.get(key) != expected:
                return False
        return True

    def _resolve_service_url(self, namespace: str, workload: str) -> str:
        try:
            service = self.k8s.get_service_raw(namespace=namespace, name=workload)
            return self._service_to_url(service)
        except Exception:
            services = self.k8s.list_services_raw(namespace=namespace)
            for service in services:
                selector = service.get("spec", {}).get("selector") or {}
                if selector.get("app") == workload:
                    return self._service_to_url(service)
            raise LlmInferenceError(404, f"no Kubernetes Service found for workload: {namespace}/{workload}")

    def _service_to_url(self, service: dict[str, Any]) -> str:
        spec = service.get("spec") or {}
        cluster_ip = str(spec.get("cluster_ip") or spec.get("clusterIP") or "").strip()
        if not cluster_ip or cluster_ip.lower() == "none":
            raise LlmInferenceError(404, "workload service has no reachable ClusterIP")

        ports = spec.get("ports") or []
        if not ports:
            raise LlmInferenceError(404, "workload service exposes no ports")

        port = int(ports[0].get("port") or 8000)
        return f"http://{cluster_ip}:{port}/v1/chat/completions"

    @staticmethod
    def _service_ref(namespace: str, workload: str) -> str:
        return f"{namespace}/{workload}"

    def _run_path(self, run_id: str) -> Path:
        return self.runs_root / f"{run_id}.json"

    def _write_run_state(self, run_id: str, state: dict[str, Any]) -> None:
        path = self._run_path(run_id)
        temp_path = path.with_name(f"{path.stem}.{time.time_ns()}.tmp")
        temp_path.write_text(json.dumps(state, ensure_ascii=True), encoding="utf-8")
        temp_path.replace(path)

    def _read_run_state(self, run_id: str) -> dict[str, Any]:
        path = self._run_path(run_id)
        if not path.exists():
            raise KeyError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _initial_progress_state() -> dict[str, Any]:
        return {
            "elapsed_seconds": 0.0,
            "completed_requests": 0,
            "failed_requests": 0,
            "prompt_tokens_so_far": 0.0,
            "completion_tokens_so_far": 0.0,
            "total_tokens_so_far": 0.0,
            "current_request_throughput_rps": 0.0,
            "current_prompt_tps": 0.0,
            "current_generation_tps": 0.0,
            "current_total_tps": 0.0,
            "buckets": [],
        }

    @staticmethod
    def _round_metric(value: float) -> float:
        return round(float(value), 3)

    @staticmethod
    def _empty_bucket(second: int) -> dict[str, Any]:
        return {
            "second": second,
            "completed_requests": 0,
            "failed_requests": 0,
            "prompt_tokens": 0.0,
            "completion_tokens": 0.0,
            "total_tokens": 0.0,
        }

    def _ensure_bucket_range(self, progress: dict[str, Any], bucket_second: int) -> list[dict[str, Any]]:
        buckets: list[dict[str, Any]] = progress["buckets"]
        if not buckets:
            buckets.append(self._empty_bucket(bucket_second))
            return buckets

        last_second = int(buckets[-1]["second"])
        if bucket_second <= last_second:
            return buckets

        for second in range(last_second + 1, bucket_second + 1):
            buckets.append(self._empty_bucket(second))
        return buckets

    def _update_run_progress(
        self,
        *,
        state: dict[str, Any],
        started_monotonic: float,
        completed_delta: int = 0,
        failed_delta: int = 0,
        prompt_tokens_delta: float = 0.0,
        completion_tokens_delta: float = 0.0,
        total_tokens_delta: float = 0.0,
    ) -> None:
        progress = state["progress"]
        elapsed = max(time.time() - started_monotonic, 0.0)
        progress["elapsed_seconds"] = self._round_metric(elapsed)
        progress["completed_requests"] += completed_delta
        progress["failed_requests"] += failed_delta
        progress["prompt_tokens_so_far"] = self._round_metric(
            float(progress["prompt_tokens_so_far"]) + float(prompt_tokens_delta)
        )
        progress["completion_tokens_so_far"] = self._round_metric(
            float(progress["completion_tokens_so_far"]) + float(completion_tokens_delta)
        )
        progress["total_tokens_so_far"] = self._round_metric(
            float(progress["total_tokens_so_far"]) + float(total_tokens_delta)
        )

        bucket_second = int(elapsed)
        buckets = self._ensure_bucket_range(progress, bucket_second)
        bucket = buckets[-1]
        bucket["completed_requests"] += completed_delta
        bucket["failed_requests"] += failed_delta
        bucket["prompt_tokens"] = self._round_metric(float(bucket["prompt_tokens"]) + float(prompt_tokens_delta))
        bucket["completion_tokens"] = self._round_metric(
            float(bucket["completion_tokens"]) + float(completion_tokens_delta)
        )
        bucket["total_tokens"] = self._round_metric(float(bucket["total_tokens"]) + float(total_tokens_delta))

        window_buckets = buckets[-5:]
        request_count = sum(int(item["completed_requests"]) for item in window_buckets)
        prompt_sum = sum(float(item["prompt_tokens"]) for item in window_buckets)
        completion_sum = sum(float(item["completion_tokens"]) for item in window_buckets)
        total_sum = sum(float(item["total_tokens"]) for item in window_buckets)
        window_seconds = max(1, len(window_buckets))
        progress["current_request_throughput_rps"] = self._round_metric(request_count / window_seconds)
        progress["current_prompt_tps"] = self._round_metric(prompt_sum / window_seconds)
        progress["current_generation_tps"] = self._round_metric(completion_sum / window_seconds)
        progress["current_total_tps"] = self._round_metric(total_sum / window_seconds)

    def _refresh_run_progress_clock(self, state: dict[str, Any], started_monotonic: float) -> None:
        self._update_run_progress(state=state, started_monotonic=started_monotonic)

    def _build_run_state(
        self,
        *,
        run_id: str,
        namespace: str,
        workload: str,
        profile_id: str,
        profile_config: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema": "pre6g.llm_benchmark_run.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "namespace": namespace,
            "workload": workload,
            "profile": str(profile_config["display_name"]),
            "profile_id": profile_id,
            "status": "queued",
            "request_count": int(profile_config["request_count"]),
            "concurrency": int(profile_config["concurrency"]),
            "max_tokens": int(profile_config["max_tokens"]),
            "temperature": float(profile_config["temperature"]),
            "started_ts": int(time.time()),
            "finished_ts": None,
            "progress": self._initial_progress_state(),
            "result": None,
            "error": None,
        }

    def _benchmark_result_paths(self, run_id: str) -> tuple[str, str]:
        return f"/tmp/{run_id}.json", f"/tmp/{run_id}.log"

    def _resolve_offline_bench_target(self) -> tuple[str, str]:
        namespace = self.offline_bench_namespace
        target = self.offline_bench_target
        if not namespace or not target:
            raise LlmInferenceError(
                409,
                "offline throughput benchmark is not configured for this runtime; configure PRE6G_LLM_OFFLINE_BENCH_NAMESPACE and PRE6G_LLM_OFFLINE_BENCH_TARGET for a dedicated benchmark target",
            )
        return namespace, target

    def _build_benchmark_exec_command(
        self,
        *,
        namespace: str,
        workload: str,
        profile_config: dict[str, Any],
        run_id: str,
    ) -> list[str]:
        result_path, log_path = self._benchmark_result_paths(run_id)
        service_url, _ = self._resolve_ready_target(namespace=namespace, workload=workload)
        base_url = service_url.rsplit("/v1/", 1)[0]
        model = str(profile_config["model"])
        served_model_name = str(profile_config.get("served_model_name") or model)
        shell_cmd = (
            f"rm -f {result_path} {log_path}; "
            "vllm bench serve "
            "--backend openai-chat "
            f"--base-url {base_url} "
            "--endpoint /v1/chat/completions "
            "--dataset-name random "
            f"--model {model} "
            f"--served-model-name {served_model_name} "
            f"--num-prompts {int(profile_config['request_count'])} "
            f"--input-len {int(profile_config['input_len'])} "
            f"--output-len {int(profile_config['max_tokens'])} "
            f"--max-concurrency {int(profile_config['concurrency'])} "
            f"--temperature {float(profile_config['temperature'])} "
            "--save-result "
            "--disable-tqdm "
            "--metric-percentiles 50,95,99 "
            "--percentile-metrics ttft,tpot,itl,e2el "
            "--result-dir /tmp "
            f"--result-filename {run_id}.json "
            f">{log_path} 2>&1"
        )
        return [
            self.kubectl_bin,
            "-n",
            namespace,
            "exec",
            f"deploy/{workload}",
            "--",
            "/bin/bash",
            "-lc",
            shell_cmd,
        ]

    def _build_offline_throughput_exec_command(
        self,
        *,
        profile_config: dict[str, Any],
        run_id: str,
    ) -> list[str]:
        target_namespace, target = self._resolve_offline_bench_target()
        result_path, log_path = self._benchmark_result_paths(run_id)
        model = str(profile_config["model"])
        served_model_name = str(profile_config.get("served_model_name") or model)
        gpu_memory_utilization = float(profile_config.get("gpu_memory_utilization") or 0.72)
        max_model_len = int(profile_config.get("max_model_len") or 2048)
        shell_cmd = (
            f"rm -f {result_path} {log_path}; "
            "vllm bench throughput "
            "--backend vllm "
            "--dataset-name random "
            f"--model {model} "
            f"--served-model-name {served_model_name} "
            f"--input-len {int(profile_config['input_len'])} "
            f"--output-len {int(profile_config['max_tokens'])} "
            f"--num-prompts {int(profile_config['request_count'])} "
            f"--gpu-memory-utilization {gpu_memory_utilization} "
            f"--max-model-len {max_model_len} "
            f"--output-json {result_path} "
            f">{log_path} 2>&1"
        )
        return [
            self.kubectl_bin,
            "-n",
            target_namespace,
            "exec",
            target,
            "--",
            "/bin/bash",
            "-lc",
            shell_cmd,
        ]

    def _read_offline_throughput_result_payload(self, *, run_id: str) -> dict[str, Any]:
        target_namespace, target = self._resolve_offline_bench_target()
        result_path, _ = self._benchmark_result_paths(run_id)
        command = [
            self.kubectl_bin,
            "-n",
            target_namespace,
            "exec",
            target,
            "--",
            "/bin/bash",
            "-lc",
            f"cat {result_path}",
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
        if completed.returncode != 0:
            raise LlmInferenceError(
                502,
                f"failed to read offline throughput benchmark result: {completed.stderr.strip() or completed.stdout.strip() or 'unknown error'}",
            )
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise LlmInferenceError(502, "offline throughput benchmark result was not valid JSON") from exc

    def _build_offline_throughput_result(
        self,
        *,
        namespace: str,
        workload: str,
        profile: str,
        profile_config: dict[str, Any],
        run_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        elapsed = round(float(payload.get("elapsed_time") or payload.get("duration") or 0.0), 3)
        total_output_tokens = float(payload.get("total_num_tokens") or payload.get("total_output_tokens") or 0.0)
        throughput = float(payload.get("tokens_per_second") or payload.get("throughput") or 0.0)
        completed_requests = int(payload.get("num_prompts") or payload.get("completed") or profile_config["request_count"])
        return {
            "schema": "pre6g.llm_benchmark.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "namespace": namespace,
            "workload": workload,
            "profile": str(profile_config["display_name"]),
            "profile_id": profile,
            "request_count": int(profile_config["request_count"]),
            "max_tokens": int(profile_config["max_tokens"]),
            "temperature": float(profile_config["temperature"]),
            "concurrency": int(profile_config["concurrency"]),
            "status": "succeeded",
            "completed_requests": completed_requests,
            "failed_requests": 0,
            "run_elapsed_seconds": elapsed if elapsed > 0 else None,
            "request_throughput_rps": round(completed_requests / elapsed, 3) if elapsed > 0 else None,
            "aggregate_prompt_tps": None,
            "aggregate_generation_tps": round(throughput, 3) if throughput > 0 else 0.0,
            "aggregate_total_tps": round(throughput, 3) if throughput > 0 else 0.0,
            "latency_p50_seconds": None,
            "latency_p95_seconds": None,
            "mean_latency_seconds": None,
            "mean_prompt_tokens": round(float(profile_config["input_len"]), 3),
            "mean_completion_tokens": round((total_output_tokens / max(completed_requests, 1)), 3)
            if total_output_tokens > 0
            else round(float(profile_config["max_tokens"]), 3),
            "mean_total_tokens": round(
                float(profile_config["input_len"])
                + (
                    (total_output_tokens / max(completed_requests, 1))
                    if total_output_tokens > 0
                    else float(profile_config["max_tokens"])
                ),
                3,
            ),
            "mean_ttft_seconds": None,
            "p95_ttft_seconds": None,
            "mean_tpot_seconds": None,
            "p95_tpot_seconds": None,
            "mean_itl_seconds": None,
            "p95_itl_seconds": None,
        }

    @staticmethod
    def _empty_benchmark_aggregate() -> dict[str, Any]:
        return {
            "chunks_completed": 0,
            "completed_requests": 0,
            "failed_requests": 0,
            "total_input_tokens": 0.0,
            "total_output_tokens": 0.0,
            "weighted_mean_e2el_ms": 0.0,
            "weighted_mean_ttft_ms": 0.0,
            "weighted_mean_tpot_ms": 0.0,
            "weighted_mean_itl_ms": 0.0,
        }

    def _accumulate_benchmark_payload(self, aggregate: dict[str, Any], payload: dict[str, Any]) -> None:
        completed = int(payload.get("completed") or 0)
        aggregate["chunks_completed"] += 1
        aggregate["completed_requests"] += completed
        aggregate["failed_requests"] += int(payload.get("failed") or 0)
        aggregate["total_input_tokens"] += float(payload.get("total_input_tokens") or 0.0)
        aggregate["total_output_tokens"] += float(payload.get("total_output_tokens") or 0.0)
        if completed > 0:
            aggregate["weighted_mean_e2el_ms"] += float(payload.get("mean_e2el_ms") or 0.0) * completed
            aggregate["weighted_mean_ttft_ms"] += float(payload.get("mean_ttft_ms") or 0.0) * completed
            aggregate["weighted_mean_tpot_ms"] += float(payload.get("mean_tpot_ms") or 0.0) * completed
            aggregate["weighted_mean_itl_ms"] += float(payload.get("mean_itl_ms") or 0.0) * completed

    def _build_continuous_result(
        self,
        *,
        namespace: str,
        workload: str,
        profile: str,
        profile_config: dict[str, Any],
        run_id: str,
        aggregate: dict[str, Any],
        started_monotonic: float,
        status: str,
    ) -> dict[str, Any]:
        elapsed = round(max(time.time() - started_monotonic, 0.001), 3)
        completed_requests = int(aggregate["completed_requests"])
        total_input_tokens = float(aggregate["total_input_tokens"])
        total_output_tokens = float(aggregate["total_output_tokens"])
        total_tokens = total_input_tokens + total_output_tokens
        return {
            "schema": "pre6g.llm_benchmark.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "namespace": namespace,
            "workload": workload,
            "profile": str(profile_config["display_name"]),
            "profile_id": profile,
            "request_count": int(profile_config["request_count"]),
            "max_tokens": int(profile_config["max_tokens"]),
            "temperature": float(profile_config["temperature"]),
            "concurrency": int(profile_config["concurrency"]),
            "status": status,
            "completed_requests": completed_requests,
            "failed_requests": int(aggregate["failed_requests"]),
            "run_elapsed_seconds": elapsed,
            "request_throughput_rps": round(completed_requests / elapsed, 3),
            "aggregate_prompt_tps": round(total_input_tokens / elapsed, 3) if total_input_tokens > 0 else 0.0,
            "aggregate_generation_tps": round(total_output_tokens / elapsed, 3) if total_output_tokens > 0 else 0.0,
            "aggregate_total_tps": round(total_tokens / elapsed, 3) if total_tokens > 0 else 0.0,
            "latency_p50_seconds": None,
            "latency_p95_seconds": None,
            "mean_latency_seconds": round((aggregate["weighted_mean_e2el_ms"] / max(completed_requests, 1)) / 1000.0, 3)
            if completed_requests > 0
            else None,
            "mean_prompt_tokens": round(total_input_tokens / max(completed_requests, 1), 3) if total_input_tokens > 0 else 0.0,
            "mean_completion_tokens": round(total_output_tokens / max(completed_requests, 1), 3)
            if total_output_tokens > 0
            else 0.0,
            "mean_total_tokens": round(total_tokens / max(completed_requests, 1), 3) if total_tokens > 0 else 0.0,
            "mean_ttft_seconds": round((aggregate["weighted_mean_ttft_ms"] / max(completed_requests, 1)) / 1000.0, 3)
            if completed_requests > 0
            else None,
            "p95_ttft_seconds": None,
            "mean_tpot_seconds": round((aggregate["weighted_mean_tpot_ms"] / max(completed_requests, 1)) / 1000.0, 4)
            if completed_requests > 0
            else None,
            "p95_tpot_seconds": None,
            "mean_itl_seconds": round((aggregate["weighted_mean_itl_ms"] / max(completed_requests, 1)) / 1000.0, 4)
            if completed_requests > 0
            else None,
            "p95_itl_seconds": None,
        }

    def _read_benchmark_result_payload(self, *, namespace: str, workload: str, run_id: str) -> dict[str, Any]:
        result_path, _ = self._benchmark_result_paths(run_id)
        command = [
            self.kubectl_bin,
            "-n",
            namespace,
            "exec",
            f"deploy/{workload}",
            "--",
            "/bin/bash",
            "-lc",
            f"cat {result_path}",
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
        if completed.returncode != 0:
            raise LlmInferenceError(
                502,
                f"failed to read vLLM benchmark result: {completed.stderr.strip() or completed.stdout.strip() or 'unknown error'}",
            )
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise LlmInferenceError(502, "vLLM benchmark result was not valid JSON") from exc

    def _build_benchmark_result_from_vllm(
        self,
        *,
        namespace: str,
        workload: str,
        profile: str,
        profile_config: dict[str, Any],
        run_id: str,
        payload: dict[str, Any],
        started_monotonic: float,
    ) -> dict[str, Any]:
        payload_duration = float(payload.get("duration") or 0.0)
        elapsed = round(payload_duration if payload_duration > 0 else max(time.time() - started_monotonic, 0.001), 3)
        total_input_tokens = float(payload.get("total_input_tokens") or 0.0)
        total_output_tokens = float(payload.get("total_output_tokens") or 0.0)
        completed_requests = int(payload.get("completed") or 0)
        p95_e2el_ms = payload.get("p95_e2el_ms")
        p95_ttft_ms = payload.get("p95_ttft_ms")
        p95_tpot_ms = payload.get("p95_tpot_ms")
        p95_itl_ms = payload.get("p95_itl_ms")
        return {
            "schema": "pre6g.llm_benchmark.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "namespace": namespace,
            "workload": workload,
            "profile": str(profile_config["display_name"]),
            "profile_id": profile,
            "request_count": int(profile_config["request_count"]),
            "max_tokens": int(profile_config["max_tokens"]),
            "temperature": float(profile_config["temperature"]),
            "concurrency": int(profile_config["concurrency"]),
            "status": "succeeded" if int(payload.get("failed") or 0) == 0 else "completed_with_errors",
            "completed_requests": completed_requests,
            "failed_requests": int(payload.get("failed") or 0),
            "run_elapsed_seconds": elapsed,
            "request_throughput_rps": round(float(payload.get("request_throughput") or 0.0), 3),
            "aggregate_prompt_tps": round(total_input_tokens / elapsed, 3) if elapsed > 0 and total_input_tokens > 0 else 0.0,
            "aggregate_generation_tps": round(float(payload.get("output_throughput") or 0.0), 3),
            "aggregate_total_tps": round(float(payload.get("total_token_throughput") or 0.0), 3),
            "latency_p50_seconds": round(float(payload.get("median_e2el_ms") or 0.0) / 1000.0, 3)
            if payload.get("median_e2el_ms") is not None
            else None,
            "latency_p95_seconds": round(float(p95_e2el_ms or 0.0) / 1000.0, 3)
            if p95_e2el_ms is not None
            else None,
            "mean_latency_seconds": round(float(payload.get("mean_e2el_ms") or 0.0) / 1000.0, 3)
            if payload.get("mean_e2el_ms") is not None
            else None,
            "mean_prompt_tokens": round(total_input_tokens / max(completed_requests, 1), 3) if total_input_tokens > 0 else 0.0,
            "mean_completion_tokens": round(total_output_tokens / max(completed_requests, 1), 3) if total_output_tokens > 0 else 0.0,
            "mean_total_tokens": round((total_input_tokens + total_output_tokens) / max(completed_requests, 1), 3)
            if (total_input_tokens + total_output_tokens) > 0
            else 0.0,
            "mean_ttft_seconds": round(float(payload.get("mean_ttft_ms") or 0.0) / 1000.0, 3)
            if payload.get("mean_ttft_ms") is not None
            else None,
            "p95_ttft_seconds": round(float((p95_ttft_ms if p95_ttft_ms is not None else payload.get("p99_ttft_ms")) or 0.0) / 1000.0, 3)
            if p95_ttft_ms is not None or payload.get("p99_ttft_ms") is not None
            else None,
            "mean_tpot_seconds": round(float(payload.get("mean_tpot_ms") or 0.0) / 1000.0, 4)
            if payload.get("mean_tpot_ms") is not None
            else None,
            "p95_tpot_seconds": round(float((p95_tpot_ms if p95_tpot_ms is not None else payload.get("p99_tpot_ms")) or 0.0) / 1000.0, 4)
            if p95_tpot_ms is not None or payload.get("p99_tpot_ms") is not None
            else None,
            "mean_itl_seconds": round(float(payload.get("mean_itl_ms") or 0.0) / 1000.0, 4)
            if payload.get("mean_itl_ms") is not None
            else None,
            "p95_itl_seconds": round(float((p95_itl_ms if p95_itl_ms is not None else payload.get("p99_itl_ms")) or 0.0) / 1000.0, 4)
            if p95_itl_ms is not None or payload.get("p99_itl_ms") is not None
            else None,
        }

    def _finalize_run_result(
        self,
        *,
        namespace: str,
        workload: str,
        profile: str,
        profile_config: dict[str, Any],
        run_id: str,
        completed: int,
        failed: int,
        started_monotonic: float,
        latencies: list[Optional[float]],
        prompt_tokens: list[Optional[float]],
        completion_tokens: list[Optional[float]],
        total_tokens: list[Optional[float]],
    ) -> dict[str, Any]:
        elapsed = round(max(time.time() - started_monotonic, 0.001), 3)
        prompt_sum = sum(float(value) for value in prompt_tokens if value is not None)
        completion_sum = sum(float(value) for value in completion_tokens if value is not None)
        total_sum = sum(float(value) for value in total_tokens if value is not None)
        return {
            "schema": "pre6g.llm_benchmark.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "namespace": namespace,
            "workload": workload,
            "profile": str(profile_config["display_name"]),
            "profile_id": profile,
            "request_count": int(profile_config["request_count"]),
            "max_tokens": int(profile_config["max_tokens"]),
            "temperature": float(profile_config["temperature"]),
            "concurrency": int(profile_config["concurrency"]),
            "status": "succeeded" if failed == 0 else "completed_with_errors",
            "completed_requests": completed,
            "failed_requests": failed,
            "run_elapsed_seconds": elapsed,
            "request_throughput_rps": round(completed / elapsed, 3),
            "aggregate_prompt_tps": round(prompt_sum / elapsed, 3) if prompt_sum > 0 else 0.0,
            "aggregate_generation_tps": round(completion_sum / elapsed, 3) if completion_sum > 0 else 0.0,
            "aggregate_total_tps": round(total_sum / elapsed, 3) if total_sum > 0 else 0.0,
            "latency_p50_seconds": self._percentile(latencies, 0.50),
            "latency_p95_seconds": self._percentile(latencies, 0.95),
            "mean_latency_seconds": self._mean(latencies),
            "mean_prompt_tokens": self._mean(prompt_tokens),
            "mean_completion_tokens": self._mean(completion_tokens),
            "mean_total_tokens": self._mean(total_tokens),
            "mean_ttft_seconds": None,
            "p95_ttft_seconds": None,
            "mean_tpot_seconds": None,
            "p95_tpot_seconds": None,
            "mean_itl_seconds": None,
            "p95_itl_seconds": None,
        }

    def _resolve_ready_target(self, namespace: str, workload: str) -> tuple[str, str]:
        workload_status = self.workloads.get_workload_status(namespace=namespace, workload=workload)
        if workload_status.replica_summary.ready <= 0:
            raise LlmInferenceError(409, f"workload is not ready: {namespace}/{workload}")

        service_url = self._resolve_service_url(namespace=namespace, workload=workload)
        model_name = (
            workload_status.identity.served_model_id
            or workload_status.identity.model_name
            or workload_status.identity.workload
        )
        return service_url, model_name

    @staticmethod
    def _extract_response_text(payload: dict[str, Any]) -> Optional[str]:
        choices = payload.get("choices") or []
        if not choices:
            return None
        first = choices[0] or {}
        message = first.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        return None

    @staticmethod
    def _extract_finish_reason(payload: dict[str, Any]) -> Optional[str]:
        choices = payload.get("choices") or []
        if not choices:
            return None
        return choices[0].get("finish_reason")

    def _execute_inference_request(
        self,
        *,
        service_url: str,
        model_name: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        request_payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        started = time.time()
        try:
            response = requests.post(
                service_url,
                json=request_payload,
                timeout=self.request_timeout_seconds,
            )
        except requests.Timeout as exc:
            raise LlmInferenceError(504, f"vLLM inference timed out after {self.request_timeout_seconds:.0f}s") from exc
        except requests.RequestException as exc:
            raise LlmInferenceError(502, f"failed to reach vLLM service: {exc}") from exc
        latency_seconds = round(time.time() - started, 3)

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {}

        if response.status_code >= 400:
            detail = response_payload.get("error") if isinstance(response_payload, dict) else None
            if isinstance(detail, dict):
                detail = detail.get("message") or str(detail)
            raise LlmInferenceError(
                response.status_code,
                str(detail or f"vLLM returned HTTP {response.status_code}"),
            )

        usage = response_payload.get("usage") or {}
        result = {
            "http_status": response.status_code,
            "latency_seconds": latency_seconds,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "finish_reason": self._extract_finish_reason(response_payload),
            "response_text": self._extract_response_text(response_payload),
        }
        return result

    def run_inference(
        self,
        *,
        namespace: str,
        workload: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        record_history: bool = True,
    ) -> dict[str, Any]:
        service_url, model_name = self._resolve_ready_target(namespace=namespace, workload=workload)
        result = self._execute_inference_request(
            service_url=service_url,
            model_name=model_name,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        result.update(
            {
                "schema": "pre6g.llm_inference.v1",
                "ts": int(time.time()),
                "namespace": namespace,
                "workload": workload,
                "target_service": self._service_ref(namespace, workload),
                "model": model_name,
            }
        )
        if record_history:
            self._append_history(
                {
                    "ts": result["ts"],
                    "event_type": "single_inference",
                    "namespace": namespace,
                    "workload": workload,
                    "status": "succeeded",
                    "model": model_name,
                    "latency_seconds": result["latency_seconds"],
                    "prompt_char_count": len(prompt),
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "prompt_tokens": result["prompt_tokens"],
                    "completion_tokens": result["completion_tokens"],
                    "total_tokens": result["total_tokens"],
                    "finish_reason": result["finish_reason"],
                }
            )
        return result

    @staticmethod
    def _mean(values: list[Optional[float]]) -> Optional[float]:
        filtered = [float(value) for value in values if value is not None]
        if not filtered:
            return None
        return round(sum(filtered) / len(filtered), 3)

    @staticmethod
    def _percentile(values: list[Optional[float]], ratio: float) -> Optional[float]:
        filtered = sorted(float(value) for value in values if value is not None)
        if not filtered:
            return None
        index = max(0, min(len(filtered) - 1, int(round((len(filtered) - 1) * ratio))))
        return round(filtered[index], 3)

    def run_benchmark_profile(self, *, namespace: str, workload: str, profile: str) -> dict[str, Any]:
        profile_config = self.BENCHMARK_PROFILES.get(profile)
        if not profile_config:
            raise LlmInferenceError(404, f"unknown benchmark profile: {profile}")
        run_id = f"{profile}-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        started = time.time()
        command = self._build_benchmark_exec_command(
            namespace=namespace,
            workload=workload,
            profile_config=profile_config,
            run_id=run_id,
        )
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.benchmark_timeout_seconds,
        )
        if completed.returncode != 0:
            raise LlmInferenceError(
                502,
                f"vLLM bench serve failed: {completed.stderr.strip() or completed.stdout.strip() or f'exit code {completed.returncode}'}",
            )
        result_payload = self._read_benchmark_result_payload(
            namespace=namespace,
            workload=workload,
            run_id=run_id,
        )
        result = self._build_benchmark_result_from_vllm(
            namespace=namespace,
            workload=workload,
            profile=profile,
            profile_config=profile_config,
            run_id=run_id,
            payload=result_payload,
            started_monotonic=started,
        )
        self._append_history(
            {
                "ts": result["ts"],
                "event_type": "serving_benchmark",
                "namespace": namespace,
                "workload": workload,
                "status": result["status"],
                "run_id": run_id,
                "profile": result["profile"],
                "profile_id": profile,
                "request_count": result["request_count"],
                "concurrency": result["concurrency"],
                "completed_requests": result["completed_requests"],
                "failed_requests": result["failed_requests"],
                "run_elapsed_seconds": result["run_elapsed_seconds"],
                "request_throughput_rps": result["request_throughput_rps"],
                "aggregate_prompt_tps": result["aggregate_prompt_tps"],
                "aggregate_generation_tps": result["aggregate_generation_tps"],
                "aggregate_total_tps": result["aggregate_total_tps"],
                "latency_p50_seconds": result["latency_p50_seconds"],
                "latency_p95_seconds": result["latency_p95_seconds"],
                "mean_latency_seconds": result["mean_latency_seconds"],
                "mean_prompt_tokens": result["mean_prompt_tokens"],
                "mean_completion_tokens": result["mean_completion_tokens"],
                "mean_total_tokens": result["mean_total_tokens"],
                "mean_ttft_seconds": result["mean_ttft_seconds"],
                "p95_ttft_seconds": result["p95_ttft_seconds"],
                "mean_tpot_seconds": result["mean_tpot_seconds"],
                "p95_tpot_seconds": result["p95_tpot_seconds"],
                "mean_itl_seconds": result["mean_itl_seconds"],
                "p95_itl_seconds": result["p95_itl_seconds"],
            }
        )
        return result

    def start_benchmark_run(self, *, namespace: str, workload: str, profile: str) -> dict[str, Any]:
        profile_config = self.BENCHMARK_PROFILES.get(profile)
        if not profile_config:
            raise LlmInferenceError(404, f"unknown benchmark profile: {profile}")

        self._resolve_ready_target(namespace=namespace, workload=workload)
        run_id = f"{profile}-run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        state = self._build_run_state(
            run_id=run_id,
            namespace=namespace,
            workload=workload,
            profile_id=profile,
            profile_config=profile_config,
        )
        self._write_run_state(run_id, state)
        cancel_event = Event()
        with self._run_state_lock:
            self._active_run_controls[run_id] = {"cancel_event": cancel_event, "process": None}

        thread = Thread(
            target=self._run_benchmark_background,
            kwargs={
                "run_id": run_id,
                "namespace": namespace,
                "workload": workload,
                "profile": profile,
                "cancel_event": cancel_event,
            },
            daemon=True,
        )
        thread.start()
        return {
            "schema": "pre6g.llm_benchmark_run_start.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "namespace": namespace,
            "workload": workload,
            "profile": str(profile_config["display_name"]),
            "profile_id": profile,
            "status": "queued",
        }

    def _run_benchmark_background(
        self,
        *,
        run_id: str,
        namespace: str,
        workload: str,
        profile: str,
        cancel_event: Event,
    ) -> None:
        state = self._read_run_state(run_id)
        profile_config = self.BENCHMARK_PROFILES[profile]
        started = time.time()
        state["status"] = "running"
        state["started_ts"] = int(time.time())
        self._write_run_state(run_id, state)
        aggregate_totals = self._empty_benchmark_aggregate()

        try:
            chunk_index = 0
            is_continuous = bool(profile_config.get("continuous"))
            max_runtime_seconds = float(profile_config.get("max_runtime_seconds") or self.benchmark_timeout_seconds)

            while True:
                if is_continuous and (time.time() - started) >= max_runtime_seconds:
                    cancel_event.set()
                    break

                chunk_run_id = run_id if not is_continuous else f"{run_id}-chunk-{chunk_index:05d}"
                command = self._build_benchmark_exec_command(
                    namespace=namespace,
                    workload=workload,
                    profile_config=profile_config,
                    run_id=chunk_run_id,
                )
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                with self._run_state_lock:
                    control = self._active_run_controls.get(run_id)
                    if control is not None:
                        control["process"] = process

                while True:
                    state = self._read_run_state(run_id)
                    if cancel_event.is_set():
                        if process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                process.kill()
                        break

                    workload_status = self.workloads.get_workload_status(namespace=namespace, workload=workload)
                    aggregate = workload_status.aggregate
                    self._update_run_progress(state=state, started_monotonic=started)
                    progress = state["progress"]
                    if progress["buckets"]:
                        bucket = progress["buckets"][-1]
                        bucket["prompt_tokens"] = self._round_metric(float(aggregate.prompt_tokens_per_second or 0.0))
                        bucket["completion_tokens"] = self._round_metric(
                            float(aggregate.generation_tokens_per_second or 0.0)
                        )
                        bucket["total_tokens"] = self._round_metric(
                            float(aggregate.prompt_tokens_per_second or 0.0)
                            + float(aggregate.generation_tokens_per_second or 0.0)
                        )
                        progress["current_prompt_tps"] = bucket["prompt_tokens"]
                        progress["current_generation_tps"] = bucket["completion_tokens"]
                        progress["current_total_tps"] = bucket["total_tokens"]
                        progress["current_request_throughput_rps"] = self._round_metric(
                            progress["completed_requests"] / max(progress["elapsed_seconds"], 1.0)
                        )
                    state["ts"] = int(time.time())
                    self._write_run_state(run_id, state)

                    if process.poll() is not None:
                        if process.returncode != 0:
                            stderr_text = (process.stderr.read() or "").strip() if process.stderr else ""
                            raise LlmInferenceError(
                                502,
                                f"vLLM bench serve failed: {stderr_text or f'exit code {process.returncode}'}",
                            )
                        break
                    time.sleep(1.0)

                if cancel_event.is_set():
                    break

                result_payload = self._read_benchmark_result_payload(
                    namespace=namespace,
                    workload=workload,
                    run_id=chunk_run_id,
                )
                self._accumulate_benchmark_payload(aggregate_totals, result_payload)
                state = self._read_run_state(run_id)
                self._update_run_progress(
                    state=state,
                    started_monotonic=started,
                    completed_delta=int(result_payload.get("completed") or 0),
                    failed_delta=int(result_payload.get("failed") or 0),
                    prompt_tokens_delta=float(result_payload.get("total_input_tokens") or 0.0),
                    completion_tokens_delta=float(result_payload.get("total_output_tokens") or 0.0),
                    total_tokens_delta=float(result_payload.get("total_input_tokens") or 0.0)
                    + float(result_payload.get("total_output_tokens") or 0.0),
                )
                state["ts"] = int(time.time())
                self._write_run_state(run_id, state)

                if not is_continuous:
                    break
                chunk_index += 1
        except Exception as exc:
            state = self._read_run_state(run_id)
            state["status"] = "failed"
            state["finished_ts"] = int(time.time())
            state["error"] = str(exc)
            self._update_run_progress(state=state, started_monotonic=started)
            self._write_run_state(run_id, state)
            with self._run_state_lock:
                self._active_run_controls.pop(run_id, None)
            return

        if bool(profile_config.get("continuous")):
            result = self._build_continuous_result(
                namespace=namespace,
                workload=workload,
                profile=profile,
                profile_config=profile_config,
                run_id=run_id,
                aggregate=aggregate_totals,
                started_monotonic=started,
                status="cancelled" if cancel_event.is_set() else "succeeded",
            )
            result_payload = {
                "total_input_tokens": aggregate_totals["total_input_tokens"],
                "total_output_tokens": aggregate_totals["total_output_tokens"],
            }
        else:
            result_payload = self._read_benchmark_result_payload(
                namespace=namespace,
                workload=workload,
                run_id=run_id,
            )
            result = self._build_benchmark_result_from_vllm(
                namespace=namespace,
                workload=workload,
                profile=profile,
                profile_config=profile_config,
                run_id=run_id,
                payload=result_payload,
                started_monotonic=started,
            )
        state = self._read_run_state(run_id)
        state["status"] = result["status"]
        state["finished_ts"] = int(time.time())
        state["result"] = result
        state["error"] = None
        self._update_run_progress(state=state, started_monotonic=started)
        state["progress"]["completed_requests"] = int(result["completed_requests"])
        state["progress"]["failed_requests"] = int(result["failed_requests"])
        state["progress"]["prompt_tokens_so_far"] = self._round_metric(float(result_payload.get("total_input_tokens") or 0.0))
        state["progress"]["completion_tokens_so_far"] = self._round_metric(float(result_payload.get("total_output_tokens") or 0.0))
        state["progress"]["total_tokens_so_far"] = self._round_metric(
            float(result_payload.get("total_input_tokens") or 0.0) + float(result_payload.get("total_output_tokens") or 0.0)
        )
        state["progress"]["current_request_throughput_rps"] = self._round_metric(float(result["request_throughput_rps"] or 0.0))
        state["progress"]["current_prompt_tps"] = self._round_metric(float(result["aggregate_prompt_tps"] or 0.0))
        state["progress"]["current_generation_tps"] = self._round_metric(float(result["aggregate_generation_tps"] or 0.0))
        state["progress"]["current_total_tps"] = self._round_metric(float(result["aggregate_total_tps"] or 0.0))
        state["ts"] = int(time.time())
        self._write_run_state(run_id, state)
        self._append_history(
            {
                "ts": result["ts"],
                "event_type": "serving_benchmark",
                "namespace": namespace,
                "workload": workload,
                "status": result["status"],
                "run_id": run_id,
                "profile": result["profile"],
                "profile_id": profile,
                "request_count": result["request_count"],
                "concurrency": result["concurrency"],
                "completed_requests": result["completed_requests"],
                "failed_requests": result["failed_requests"],
                "run_elapsed_seconds": result["run_elapsed_seconds"],
                "request_throughput_rps": result["request_throughput_rps"],
                "aggregate_prompt_tps": result["aggregate_prompt_tps"],
                "aggregate_generation_tps": result["aggregate_generation_tps"],
                "aggregate_total_tps": result["aggregate_total_tps"],
                "latency_p50_seconds": result["latency_p50_seconds"],
                "latency_p95_seconds": result["latency_p95_seconds"],
                "mean_latency_seconds": result["mean_latency_seconds"],
                "mean_prompt_tokens": result["mean_prompt_tokens"],
                "mean_completion_tokens": result["mean_completion_tokens"],
                "mean_total_tokens": result["mean_total_tokens"],
                "mean_ttft_seconds": result["mean_ttft_seconds"],
                "p95_ttft_seconds": result["p95_ttft_seconds"],
                "mean_tpot_seconds": result["mean_tpot_seconds"],
                "p95_tpot_seconds": result["p95_tpot_seconds"],
                "mean_itl_seconds": result["mean_itl_seconds"],
                "p95_itl_seconds": result["p95_itl_seconds"],
            }
        )
        with self._run_state_lock:
            self._active_run_controls.pop(run_id, None)

    def get_benchmark_run(self, *, run_id: str) -> dict[str, Any]:
        state = self._read_run_state(run_id)
        if state.get("status") in {"queued", "running", "cancelling"}:
            started_reference = float(state.get("started_ts") or state.get("ts") or int(time.time()))
            self._refresh_run_progress_clock(state=state, started_monotonic=started_reference)
            self._write_run_state(run_id, state)
        state["ts"] = int(time.time())
        return state

    def cancel_benchmark_run(self, *, run_id: str) -> dict[str, Any]:
        with self._run_state_lock:
            control = self._active_run_controls.get(run_id)
        if control is None:
            state = self._read_run_state(run_id)
            return {
                "schema": "pre6g.llm_benchmark_run_cancel.v1",
                "ts": int(time.time()),
                "run_id": run_id,
                "status": str(state.get("status") or "unknown"),
            }
        cancel_event = control.get("cancel_event")
        if cancel_event is not None:
            cancel_event.set()
        process = control.get("process")
        if process is not None and getattr(process, "poll", None) and process.poll() is None:
            process.terminate()
        return {
            "schema": "pre6g.llm_benchmark_run_cancel.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "status": "cancelling",
        }

    def run_smoke_benchmark(self, *, namespace: str, workload: str) -> dict[str, Any]:
        return self.run_benchmark_profile(namespace=namespace, workload=workload, profile="smoke")

    def run_offline_throughput_profile(self, *, namespace: str, workload: str, profile: str) -> dict[str, Any]:
        profile_config = self.OFFLINE_THROUGHPUT_PROFILES.get(profile)
        if not profile_config:
            raise LlmInferenceError(404, f"unknown offline throughput profile: {profile}")
        run_id = f"offline-{profile}-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        command = self._build_offline_throughput_exec_command(
            profile_config=profile_config,
            run_id=run_id,
        )
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.benchmark_timeout_seconds,
        )
        if completed.returncode != 0:
            raise LlmInferenceError(
                502,
                f"vLLM bench throughput failed: {completed.stderr.strip() or completed.stdout.strip() or f'exit code {completed.returncode}'}",
            )
        payload = self._read_offline_throughput_result_payload(run_id=run_id)
        result = self._build_offline_throughput_result(
            namespace=namespace,
            workload=workload,
            profile=profile,
            profile_config=profile_config,
            run_id=run_id,
            payload=payload,
        )
        self._append_history(
            {
                "ts": result["ts"],
                "event_type": "offline_throughput_benchmark",
                "namespace": namespace,
                "workload": workload,
                "status": result["status"],
                "run_id": run_id,
                "profile": result["profile"],
                "profile_id": profile,
                "request_count": result["request_count"],
                "concurrency": result["concurrency"],
                "completed_requests": result["completed_requests"],
                "failed_requests": result["failed_requests"],
                "run_elapsed_seconds": result["run_elapsed_seconds"],
                "request_throughput_rps": result["request_throughput_rps"],
                "aggregate_generation_tps": result["aggregate_generation_tps"],
                "aggregate_total_tps": result["aggregate_total_tps"],
                "mean_prompt_tokens": result["mean_prompt_tokens"],
                "mean_completion_tokens": result["mean_completion_tokens"],
                "mean_total_tokens": result["mean_total_tokens"],
            }
        )
        return result

    def _append_history(self, item: dict[str, Any]) -> None:
        with self.history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=True) + "\n")

    def get_history(
        self,
        *,
        namespace: str | None = None,
        workload: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if self.history_path.exists():
            with self.history_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if namespace and item.get("namespace") != namespace:
                        continue
                    if workload and item.get("workload") != workload:
                        continue
                    items.append(item)

        items.sort(key=lambda item: int(item.get("ts") or 0), reverse=True)
        trimmed = items[: max(1, min(limit, 100))]
        return {
            "schema": "pre6g.llm_run_history.v1",
            "ts": int(time.time()),
            "count": len(trimmed),
            "items": trimmed,
        }
