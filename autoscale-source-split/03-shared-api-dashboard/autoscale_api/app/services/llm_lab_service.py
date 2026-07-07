import os
import time
import json
import hashlib
import subprocess
import statistics
import queue
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
            "model": "unsloth/gemma-4-E2B-it-GGUF",
            "served_model_name": "gemma-4-E2B-it-Q4_K_M.gguf",
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
            "model": "unsloth/gemma-4-E2B-it-GGUF",
            "served_model_name": "gemma-4-E2B-it-Q4_K_M.gguf",
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
    LLAMACPP_OFFLINE_PROFILES: dict[str, dict[str, Any]] = {
        "pascal-smoke": {
            "display_name": "Smoke",
            "description": "CUDA, GGUF, GPU offload, and parser verification.",
            "n_prompt": 128,
            "n_gen": 64,
            "pg_pair": "128,64",
            "n_depth": 0,
            "batch_size": 256,
            "ubatch_size": 128,
            "repetitions": 3,
            "flash_attention": "off",
            "gpu_layers": -1,
        },
        "pascal-continuous": {
            "display_name": "Continuous",
            "description": "Repeated offline throughput benchmark for live progress observation and longer hardware capacity tracking.",
            "n_prompt": 512,
            "n_gen": 128,
            "pg_pair": "512,128",
            "n_depth": 0,
            "batch_size": 512,
            "ubatch_size": 128,
            "repetitions": 0,
            "flash_attention": "off",
            "gpu_layers": -1,
            "continuous": True,
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
        self.llamacpp_offline_namespace = (
            os.getenv("PRE6G_LLAMACPP_OFFLINE_NAMESPACE", "ai-serving").strip() or "ai-serving"
        )
        self.llamacpp_offline_target = (
            os.getenv("PRE6G_LLAMACPP_OFFLINE_TARGET", "deploy/llamacpp-gemma4-e2b-q4km-bench").strip()
            or "deploy/llamacpp-gemma4-e2b-q4km-bench"
        )
        self.llamacpp_offline_target_pod = self.llamacpp_offline_target.split("/", 1)[-1]
        self.llamacpp_offline_node_name = (
            os.getenv("PRE6G_LLAMACPP_OFFLINE_NODE_NAME", "icclz1").strip() or "icclz1"
        )
        self.llamacpp_runtime_image = (
            os.getenv(
                "PRE6G_LLAMACPP_RUNTIME_IMAGE",
                "pre6g/llamacpp-cuda118-sm61:gemma4-e2b-q4km",
            ).strip()
            or "pre6g/llamacpp-cuda118-sm61:gemma4-e2b-q4km"
        )
        self.llamacpp_runtime_image_tag = (
            os.getenv("PRE6G_LLAMACPP_RUNTIME_IMAGE_TAG", "gemma4-e2b-q4km").strip()
            or "gemma4-e2b-q4km"
        )
        self.llamacpp_runtime = "llamacpp"
        self.llamacpp_benchmark_mode = "offline"
        self.llamacpp_cuda_version = os.getenv("PRE6G_LLAMACPP_CUDA_VERSION", "11.8").strip() or "11.8"
        self.llamacpp_gpu_model = (
            os.getenv("PRE6G_LLAMACPP_GPU_MODEL", "NVIDIA GeForce GTX 1080 Ti").strip()
            or "NVIDIA GeForce GTX 1080 Ti"
        )
        self.llamacpp_gpu_arch = os.getenv("PRE6G_LLAMACPP_GPU_ARCH", "sm61").strip() or "sm61"
        self.llamacpp_gpu_resource_request = (
            os.getenv("PRE6G_LLAMACPP_GPU_RESOURCE_REQUEST", "nvidia.com/gpu.shared: 1").strip()
            or "nvidia.com/gpu.shared: 1"
        )
        self.llamacpp_model_name = (
            os.getenv("PRE6G_LLAMACPP_MODEL_NAME", "Gemma 4 E2B it").strip()
            or "Gemma 4 E2B it"
        )
        self.llamacpp_model_source = (
            os.getenv(
                "PRE6G_LLAMACPP_MODEL_SOURCE",
                "unsloth/gemma-4-E2B-it-GGUF",
            ).strip()
            or "unsloth/gemma-4-E2B-it-GGUF"
        )
        self.llamacpp_quantization = os.getenv("PRE6G_LLAMACPP_QUANTIZATION", "Q4_K_M").strip() or "Q4_K_M"
        self.llamacpp_gguf_filename = (
            os.getenv(
                "PRE6G_LLAMACPP_GGUF_FILENAME",
                "gemma-4-E2B-it-Q4_K_M.gguf",
            ).strip()
            or "gemma-4-E2B-it-Q4_K_M.gguf"
        )
        self.llamacpp_gguf_path = (
            os.getenv(
                "PRE6G_LLAMACPP_GGUF_PATH",
                "/models/gemma/gemma-4-E2B-it-Q4_K_M.gguf",
            ).strip()
            or "/models/gemma/gemma-4-E2B-it-Q4_K_M.gguf"
        )
        self.llamacpp_gguf_sha256 = (
            os.getenv(
                "PRE6G_LLAMACPP_GGUF_SHA256",
                "9378bc471710229ef165709b62e34bfb62231420ddaf6d729e727305b5b8672d",
            ).strip()
            or "9378bc471710229ef165709b62e34bfb62231420ddaf6d729e727305b5b8672d"
        )
        self.llamacpp_ref = os.getenv("PRE6G_LLAMACPP_REF", "b9870").strip() or "b9870"
        self.llamacpp_commit = os.getenv("PRE6G_LLAMACPP_COMMIT", "2d97363").strip() or "2d97363"

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

    def _llamacpp_runtime_overview(self) -> dict[str, Any]:
        return {
            "runtime": self.llamacpp_runtime,
            "benchmark_mode": self.llamacpp_benchmark_mode,
            "runtime_image": self.llamacpp_runtime_image,
            "runtime_image_tag": self.llamacpp_runtime_image_tag,
            "llama_cpp_ref": self.llamacpp_ref,
            "llama_cpp_commit": self.llamacpp_commit,
            "cuda_version": self.llamacpp_cuda_version,
            "gpu_model": self.llamacpp_gpu_model,
            "gpu_arch": self.llamacpp_gpu_arch,
            "gpu_resource_request": self.llamacpp_gpu_resource_request,
            "namespace": self.llamacpp_offline_namespace,
            "target_pod": self.llamacpp_offline_target_pod,
            "node_name": self.llamacpp_offline_node_name,
            "model_name": self.llamacpp_model_name,
            "model_source": self.llamacpp_model_source,
            "gguf_filename": self.llamacpp_gguf_filename,
            "gguf_path": self.llamacpp_gguf_path,
            "gguf_sha256": self.llamacpp_gguf_sha256,
            "quantization": self.llamacpp_quantization,
            "gpu_layers": "all",
        }

    @staticmethod
    def _llamacpp_record_float(record: dict[str, Any], *keys: str) -> Optional[float]:
        for key in keys:
            if key not in record:
                continue
            value = record.get(key)
            if value is None:
                continue
            try:
                return round(float(value), 3)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _llamacpp_record_int(record: dict[str, Any], *keys: str) -> Optional[int]:
        for key in keys:
            if key not in record:
                continue
            value = record.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    def _resolve_llamacpp_profile(self, profile: str) -> dict[str, Any]:
        profile_config = self.LLAMACPP_OFFLINE_PROFILES.get(profile)
        if not profile_config:
            raise LlmInferenceError(404, f"unknown llama.cpp offline benchmark profile: {profile}")
        return profile_config

    def _build_llamacpp_run_state(
        self,
        *,
        run_id: str,
        profile_id: str,
        profile_config: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema": "pre6g.llamacpp_offline_benchmark_run.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "runtime": self.llamacpp_runtime,
            "benchmark_mode": self.llamacpp_benchmark_mode,
            "profile": str(profile_config["display_name"]),
            "profile_id": profile_id,
            "status": "queued",
            "namespace": self.llamacpp_offline_namespace,
            "target_pod": self.llamacpp_offline_target_pod,
            "node_name": self.llamacpp_offline_node_name,
            "started_at_ts": None,
            "completed_at_ts": None,
            "progress": {
                "elapsed_seconds": 0.0,
                "completed_steps": 0,
                "total_steps": int(profile_config["repetitions"]),
                "current_prompt_tps": None,
                "current_generation_tps": None,
                "current_prompt_generation_tps": None,
                "latest_completed_step_prompt_tps": None,
                "latest_completed_step_generation_tps": None,
                "latest_completed_step_prompt_generation_tps": None,
                "mean_prompt_tps": None,
                "mean_generation_tps": None,
                "mean_prompt_generation_tps": None,
                "current_phase": None,
                "current_phase_detail": None,
                "live_sample_count": 0,
                "live_buckets": [],
                "buckets": [],
            },
            "result": None,
            "error": None,
        }

    @staticmethod
    def _terminate_process(process: Any) -> None:
        if process is None or getattr(process, "poll", None) is None:
            return
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    def _build_llamacpp_preflight_exec_command(self) -> list[str]:
        return [
            self.kubectl_bin,
            "-n",
            self.llamacpp_offline_namespace,
            "exec",
            self.llamacpp_offline_target,
            "--",
            "/bin/bash",
            "-lc",
            "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader || true",
        ]

    def _build_llamacpp_exec_command(
        self,
        *,
        profile_config: dict[str, Any],
        run_id: str,
        repetitions_override: int | None = None,
    ) -> list[str]:
        repetitions = int(repetitions_override or profile_config["repetitions"])
        shell_cmd = (
            "llama-bench "
            "--progress "
            f"--model {self.llamacpp_gguf_path} "
            f"--n-prompt {int(profile_config['n_prompt'])} "
            f"--n-gen {int(profile_config['n_gen'])} "
            f"-pg {profile_config['pg_pair']} "
            f"--n-depth {int(profile_config['n_depth'])} "
            f"--batch-size {int(profile_config['batch_size'])} "
            f"--ubatch-size {int(profile_config['ubatch_size'])} "
            f"--n-gpu-layers {int(profile_config['gpu_layers'])} "
            f"--flash-attn {profile_config['flash_attention']} "
            f"--repetitions {repetitions} "
            "--output jsonl "
            "2>&1"
        )
        return [
            self.kubectl_bin,
            "-n",
            self.llamacpp_offline_namespace,
            "exec",
            self.llamacpp_offline_target,
            "--",
            "/bin/bash",
            "-lc",
            shell_cmd,
        ]

    @staticmethod
    def _parse_gpu_preflight_output(output: str) -> list[dict[str, Any]]:
        processes: list[dict[str, Any]] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                continue
            pid_text, process_name, used_memory = parts[0], parts[1], ",".join(parts[2:]).strip()
            try:
                pid = int(pid_text)
            except ValueError:
                pid = None
            processes.append(
                {
                    "pid": pid,
                    "process_name": process_name or None,
                    "used_memory": used_memory or None,
                }
            )
        return processes

    def _run_llamacpp_gpu_preflight(self) -> list[dict[str, Any]]:
        completed = subprocess.run(
            self._build_llamacpp_preflight_exec_command(),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise LlmInferenceError(
                502,
                f"failed llama.cpp GPU preflight: {completed.stderr.strip() or completed.stdout.strip() or 'unknown error'}",
            )
        return self._parse_gpu_preflight_output(completed.stdout)

    def _parse_llamacpp_benchmark_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload_meta = payload if isinstance(payload, dict) else {}
        raw_results = payload_meta.get("results", payload if isinstance(payload, list) else [])
        if isinstance(raw_results, dict):
            raw_results = [raw_results]
        if not isinstance(raw_results, list):
            raise LlmInferenceError(502, "llama.cpp benchmark result did not contain a result list")

        tests: dict[str, dict[str, Any]] = {}
        for record in raw_results:
            if not isinstance(record, dict):
                continue
            test_name = str(record.get("test") or record.get("benchmark") or record.get("kind") or "").strip().lower()
            if not test_name:
                prompt_tokens = self._llamacpp_record_int(record, "n_prompt", "prompt_tokens") or 0
                gen_tokens = self._llamacpp_record_int(record, "n_gen", "gen_tokens") or 0
                if prompt_tokens > 0 and gen_tokens == 0:
                    test_name = "pp"
                elif prompt_tokens == 0 and gen_tokens > 0:
                    test_name = "tg"
                elif prompt_tokens > 0 and gen_tokens > 0:
                    test_name = "pg"
            if not test_name:
                continue
            tests[test_name] = record

        if "pp" not in tests and "tg" not in tests:
            raise LlmInferenceError(502, "llama.cpp benchmark result did not contain pp/tg benchmark records")

        any_record = next(iter(tests.values()))
        pp_record = tests.get("pp", {})
        tg_record = tests.get("tg", {})
        pg_record = tests.get("pg", {})

        return {
            "prompt_tps_mean": self._llamacpp_record_float(
                pp_record, "avg_ts", "avg_tps", "tokens_per_second_avg", "tps_avg", "mean_tps"
            ),
            "prompt_tps_stddev": self._llamacpp_record_float(
                pp_record, "stdev_ts", "stddev_tps", "tokens_per_second_stddev", "tps_stddev"
            ),
            "generation_tps_mean": self._llamacpp_record_float(
                tg_record, "avg_ts", "avg_tps", "tokens_per_second_avg", "tps_avg", "mean_tps"
            ),
            "generation_tps_stddev": self._llamacpp_record_float(
                tg_record, "stdev_ts", "stddev_tps", "tokens_per_second_stddev", "tps_stddev"
            ),
            "prompt_generation_tps_mean": self._llamacpp_record_float(
                pg_record, "avg_ts", "avg_tps", "tokens_per_second_avg", "tps_avg", "mean_tps"
            ),
            "prompt_generation_tps_stddev": self._llamacpp_record_float(
                pg_record, "stdev_ts", "stddev_tps", "tokens_per_second_stddev", "tps_stddev"
            ),
            "n_prompt": self._llamacpp_record_int(any_record, "n_prompt", "prompt_tokens"),
            "n_gen": self._llamacpp_record_int(any_record, "n_gen", "gen_tokens"),
            "n_depth": self._llamacpp_record_int(any_record, "n_depth", "ctx"),
            "batch_size": self._llamacpp_record_int(any_record, "n_batch", "batch_size"),
            "ubatch_size": self._llamacpp_record_int(any_record, "n_ubatch", "ubatch_size"),
            "n_gpu_layers": self._llamacpp_record_int(any_record, "n_gpu_layers", "gpu_layers"),
            "repetitions": self._llamacpp_record_int(
                payload_meta, "repetitions", "n_reps"
            ),
            "flash_attention": str(
                any_record.get("flash_attn")
                or any_record.get("flash_attention")
                or payload_meta.get("flash_attention")
                or "off"
            ),
        }

    @staticmethod
    def _classify_llamacpp_record(record: dict[str, Any]) -> str | None:
        prompt_tokens = LlmLabService._llamacpp_record_int(record, "n_prompt", "prompt_tokens") or 0
        gen_tokens = LlmLabService._llamacpp_record_int(record, "n_gen", "gen_tokens") or 0
        if prompt_tokens > 0 and gen_tokens == 0:
            return "pp"
        if prompt_tokens == 0 and gen_tokens > 0:
            return "tg"
        if prompt_tokens > 0 and gen_tokens > 0:
            return "pg"
        return None

    def _parse_llamacpp_jsonl_record(self, line: str) -> dict[str, Any] | None:
        raw = line.strip()
        if not raw or not raw.startswith("{"):
            return None
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(record, dict):
            return None
        test_name = str(record.get("test") or record.get("benchmark") or record.get("kind") or "").strip().lower()
        if not test_name:
            test_name = self._classify_llamacpp_record(record) or ""
        if test_name not in {"pp", "tg", "pg"}:
            return None
        throughput = self._llamacpp_record_float(
            record, "avg_ts", "avg_tps", "tokens_per_second_avg", "tps_avg", "mean_tps"
        )
        if throughput is None:
            return None
        return {
            "test": test_name,
            "throughput": throughput,
            "n_prompt": self._llamacpp_record_int(record, "n_prompt", "prompt_tokens"),
            "n_gen": self._llamacpp_record_int(record, "n_gen", "gen_tokens"),
            "n_depth": self._llamacpp_record_int(record, "n_depth", "ctx"),
            "batch_size": self._llamacpp_record_int(record, "n_batch", "batch_size"),
            "ubatch_size": self._llamacpp_record_int(record, "n_ubatch", "ubatch_size"),
            "n_gpu_layers": self._llamacpp_record_int(record, "n_gpu_layers", "gpu_layers"),
            "flash_attention": str(record.get("flash_attn") or record.get("flash_attention") or "off"),
            "record": record,
        }

    def _update_llamacpp_live_stream_progress(
        self,
        *,
        run_id: str,
        started_monotonic: float,
        parsed_line: dict[str, Any],
    ) -> None:
        state = self._read_run_state(run_id)
        progress = state.get("progress") or {}
        test_name = str(parsed_line["test"])
        throughput = float(parsed_line["throughput"])

        if test_name == "pp":
            progress["current_prompt_tps"] = throughput
        elif test_name == "tg":
            progress["current_generation_tps"] = throughput
        elif test_name == "pg":
            progress["current_prompt_generation_tps"] = throughput

        progress["elapsed_seconds"] = round(max(time.monotonic() - started_monotonic, 0.0), 3)
        progress["live_sample_count"] = int(progress.get("live_sample_count") or 0) + 1
        live_buckets = list(progress.get("live_buckets") or [])
        live_buckets.append(
            {
                "sample": int(progress["live_sample_count"]),
                "elapsed_seconds": progress["elapsed_seconds"],
                "phase": test_name,
                "prompt_tps": progress.get("current_prompt_tps"),
                "generation_tps": progress.get("current_generation_tps"),
                "prompt_generation_tps": progress.get("current_prompt_generation_tps"),
            }
        )
        progress["live_buckets"] = live_buckets[-240:]
        state["ts"] = int(time.time())
        state["progress"] = progress
        self._write_run_state(run_id, state)

    def _update_llamacpp_phase_progress(
        self,
        *,
        run_id: str,
        started_monotonic: float,
        phase_line: str,
    ) -> None:
        state = self._read_run_state(run_id)
        progress = state.get("progress") or {}
        progress["elapsed_seconds"] = round(max(time.monotonic() - started_monotonic, 0.0), 3)
        progress["current_phase_detail"] = phase_line.strip()
        if "warmup prompt run" in phase_line:
            progress["current_phase"] = "warmup_prompt"
        elif "warmup generation run" in phase_line:
            progress["current_phase"] = "warmup_generation"
        elif "prompt run" in phase_line and "generation" not in phase_line:
            progress["current_phase"] = "prompt"
        elif "generation run" in phase_line:
            progress["current_phase"] = "generation"
        elif "starting" in phase_line:
            progress["current_phase"] = "starting"
        state["ts"] = int(time.time())
        state["progress"] = progress
        self._write_run_state(run_id, state)

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
                    "runtime": "vllm",
                    "benchmark_mode": "serving",
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
                "runtime": "vllm",
                "benchmark_mode": "serving",
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
            self._active_run_controls[run_id] = {"kind": "vllm_serving", "cancel_event": cancel_event, "process": None}

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
                "runtime": "vllm",
                "benchmark_mode": "serving",
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
                "runtime": "vllm",
                "benchmark_mode": "offline",
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

    def get_llamacpp_offline_profiles(self) -> dict[str, Any]:
        profiles = []
        for profile_id, profile_config in self.LLAMACPP_OFFLINE_PROFILES.items():
            profiles.append(
                {
                    "profile_id": profile_id,
                    "display_name": str(profile_config["display_name"]),
                    "description": str(profile_config["description"]),
                    "runtime": self.llamacpp_runtime,
                    "benchmark_mode": self.llamacpp_benchmark_mode,
                    "n_prompt": int(profile_config["n_prompt"]),
                    "n_gen": int(profile_config["n_gen"]),
                    "pg_pair": str(profile_config["pg_pair"]),
                    "n_depth": int(profile_config["n_depth"]),
                    "batch_size": int(profile_config["batch_size"]),
                    "ubatch_size": int(profile_config["ubatch_size"]),
                    "repetitions": int(profile_config["repetitions"]),
                    "flash_attention": str(profile_config["flash_attention"]),
                    "gpu_layers": int(profile_config["gpu_layers"]),
                }
            )
        return {
            "schema": "pre6g.llamacpp_offline_benchmark_profiles.v1",
            "ts": int(time.time()),
            "runtime": self.llamacpp_runtime,
            "benchmark_mode": self.llamacpp_benchmark_mode,
            "profiles": profiles,
        }

    def _build_llamacpp_result(
        self,
        *,
        run_id: str,
        profile_id: str,
        profile_config: dict[str, Any],
        parsed_result: dict[str, Any],
        gpu_processes_before: list[dict[str, Any]],
        started_at_ts: int,
        completed_at_ts: int,
        duration_seconds: float,
        status: str,
        error_summary: str | None = None,
    ) -> dict[str, Any]:
        gpu_contended = len(gpu_processes_before) > 0
        return {
            "schema": "pre6g.llamacpp_offline_benchmark.v1",
            "ts": completed_at_ts,
            "run_id": run_id,
            "runtime": self.llamacpp_runtime,
            "benchmark_mode": self.llamacpp_benchmark_mode,
            "profile": str(profile_config["display_name"]),
            "profile_id": profile_id,
            "status": status,
            "namespace": self.llamacpp_offline_namespace,
            "target_pod": self.llamacpp_offline_target_pod,
            "node_name": self.llamacpp_offline_node_name,
            "runtime_overview": self._llamacpp_runtime_overview(),
            "observed_at_ts": completed_at_ts,
            "started_at_ts": started_at_ts,
            "completed_at_ts": completed_at_ts,
            "duration_seconds": round(duration_seconds, 3),
            "prompt_tps_mean": parsed_result.get("prompt_tps_mean"),
            "prompt_tps_stddev": parsed_result.get("prompt_tps_stddev"),
            "generation_tps_mean": parsed_result.get("generation_tps_mean"),
            "generation_tps_stddev": parsed_result.get("generation_tps_stddev"),
            "prompt_generation_tps_mean": parsed_result.get("prompt_generation_tps_mean"),
            "prompt_generation_tps_stddev": parsed_result.get("prompt_generation_tps_stddev"),
            "waiting_requests": None,
            "kv_cache_usage_percent": None,
            "n_prompt": int(parsed_result.get("n_prompt") or profile_config["n_prompt"]),
            "n_gen": int(parsed_result.get("n_gen") or profile_config["n_gen"]),
            "n_depth": int(parsed_result.get("n_depth") or profile_config["n_depth"]),
            "batch_size": int(parsed_result.get("batch_size") or profile_config["batch_size"]),
            "ubatch_size": int(parsed_result.get("ubatch_size") or profile_config["ubatch_size"]),
            "n_gpu_layers": int(parsed_result.get("n_gpu_layers") or profile_config["gpu_layers"]),
            "repetitions": int(parsed_result.get("repetitions") or profile_config["repetitions"]),
            "flash_attention": str(parsed_result.get("flash_attention") or profile_config["flash_attention"]),
            "gpu_processes_before": gpu_processes_before,
            "gpu_process_count_before": len(gpu_processes_before),
            "gpu_contended": gpu_contended,
            "gpu_preflight_status": "Contended" if gpu_contended else "Idle",
            "preflight_warning": (
                "Contended GPU — throughput may not represent an isolated baseline."
                if gpu_contended
                else None
            ),
            "error_summary": error_summary,
        }

    @staticmethod
    def _llamacpp_mean(values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 3)

    @staticmethod
    def _llamacpp_stddev(values: list[float]) -> float | None:
        if len(values) < 2:
            return None
        return round(float(statistics.pstdev(values)), 3)

    def _update_llamacpp_progress(
        self,
        *,
        run_id: str,
        step: int,
        total_steps: int,
        step_duration_seconds: float,
        started_monotonic: float,
        parsed_result: dict[str, Any],
        prompt_samples: list[float],
        generation_samples: list[float],
        pg_samples: list[float],
    ) -> None:
        state = self._read_run_state(run_id)
        progress = state.get("progress") or {}
        progress["elapsed_seconds"] = round(max(time.monotonic() - started_monotonic, 0.0), 3)
        progress["completed_steps"] = step
        progress["total_steps"] = total_steps
        progress["latest_completed_step_prompt_tps"] = parsed_result.get("prompt_tps_mean")
        progress["latest_completed_step_generation_tps"] = parsed_result.get("generation_tps_mean")
        progress["latest_completed_step_prompt_generation_tps"] = parsed_result.get("prompt_generation_tps_mean")
        progress["mean_prompt_tps"] = self._llamacpp_mean(prompt_samples)
        progress["mean_generation_tps"] = self._llamacpp_mean(generation_samples)
        progress["mean_prompt_generation_tps"] = self._llamacpp_mean(pg_samples)
        progress["current_phase"] = "step_completed"
        progress["current_phase_detail"] = f"completed step {step}"
        buckets = list(progress.get("buckets") or [])
        buckets.append(
            {
                "step": step,
                "elapsed_seconds": progress["elapsed_seconds"],
                "duration_seconds": round(step_duration_seconds, 3),
                "prompt_tps": parsed_result.get("prompt_tps_mean"),
                "generation_tps": parsed_result.get("generation_tps_mean"),
                "prompt_generation_tps": parsed_result.get("prompt_generation_tps_mean"),
            }
        )
        progress["buckets"] = buckets
        state["ts"] = int(time.time())
        state["progress"] = progress
        self._write_run_state(run_id, state)

    def _mark_llamacpp_run_failed(
        self,
        *,
        run_id: str,
        profile_id: str,
        profile_config: dict[str, Any],
        started_at_ts: int | None,
        error_summary: str | None,
        gpu_processes_before: list[dict[str, Any]] | None = None,
        status: str = "failed",
    ) -> None:
        state = self._read_run_state(run_id)
        completed_at_ts = int(time.time())
        duration_seconds = 0.0
        if started_at_ts:
            duration_seconds = max(completed_at_ts - started_at_ts, 0.0)
        parsed_result: dict[str, Any] = {}
        if status == "cancelled":
            progress = state.get("progress") or {}
            buckets = list(progress.get("buckets") or [])
            prompt_samples = [
                float(bucket["prompt_tps"])
                for bucket in buckets
                if bucket.get("prompt_tps") is not None
            ]
            generation_samples = [
                float(bucket["generation_tps"])
                for bucket in buckets
                if bucket.get("generation_tps") is not None
            ]
            pg_samples = [
                float(bucket["prompt_generation_tps"])
                for bucket in buckets
                if bucket.get("prompt_generation_tps") is not None
            ]
            parsed_result = {
                "prompt_tps_mean": self._llamacpp_mean(prompt_samples),
                "prompt_tps_stddev": self._llamacpp_stddev(prompt_samples),
                "generation_tps_mean": self._llamacpp_mean(generation_samples),
                "generation_tps_stddev": self._llamacpp_stddev(generation_samples),
                "prompt_generation_tps_mean": self._llamacpp_mean(pg_samples),
                "prompt_generation_tps_stddev": self._llamacpp_stddev(pg_samples),
                "n_prompt": profile_config["n_prompt"],
                "n_gen": profile_config["n_gen"],
                "n_depth": profile_config["n_depth"],
                "batch_size": profile_config["batch_size"],
                "ubatch_size": profile_config["ubatch_size"],
                "n_gpu_layers": profile_config["gpu_layers"],
                "repetitions": profile_config["repetitions"],
                "flash_attention": profile_config["flash_attention"],
            }
        result = self._build_llamacpp_result(
            run_id=run_id,
            profile_id=profile_id,
            profile_config=profile_config,
            parsed_result=parsed_result,
            gpu_processes_before=gpu_processes_before or [],
            started_at_ts=started_at_ts or completed_at_ts,
            completed_at_ts=completed_at_ts,
            duration_seconds=duration_seconds,
            status=status,
            error_summary=error_summary,
        )
        state["ts"] = completed_at_ts
        state["status"] = status
        state["completed_at_ts"] = completed_at_ts
        state["result"] = result
        state["error"] = error_summary
        self._write_run_state(run_id, state)
        self._append_history(
            {
                "ts": completed_at_ts,
                "event_type": "llamacpp_offline_benchmark",
                "runtime": self.llamacpp_runtime,
                "benchmark_mode": self.llamacpp_benchmark_mode,
                "namespace": self.llamacpp_offline_namespace,
                "workload": self.llamacpp_offline_target_pod,
                "status": status,
                "run_id": run_id,
                "profile": str(profile_config["display_name"]),
                "profile_id": profile_id,
                "gpu_contended": bool(gpu_processes_before),
                "prompt_tps_mean": result.get("prompt_tps_mean"),
                "generation_tps_mean": result.get("generation_tps_mean"),
                "prompt_generation_tps_mean": result.get("prompt_generation_tps_mean"),
                "prompt_tps_stddev": result.get("prompt_tps_stddev"),
                "generation_tps_stddev": result.get("generation_tps_stddev"),
                "prompt_generation_tps_stddev": result.get("prompt_generation_tps_stddev"),
                "duration_seconds": result.get("duration_seconds"),
                "observed_at_ts": completed_at_ts,
                "error_summary": error_summary,
            }
        )
        with self._run_state_lock:
            self._active_run_controls.pop(run_id, None)

    def _run_llamacpp_offline_background(self, *, run_id: str, profile_id: str) -> None:
        profile_config = self._resolve_llamacpp_profile(profile_id)
        started_at_ts = int(time.time())
        started_monotonic = time.monotonic()
        gpu_processes_before: list[dict[str, Any]] = []
        with self._run_state_lock:
            control = self._active_run_controls.get(run_id) or {}
            cancel_event = control.get("cancel_event") or Event()
        state = self._read_run_state(run_id)
        state["status"] = "running"
        state["started_at_ts"] = started_at_ts
        state["ts"] = started_at_ts
        self._write_run_state(run_id, state)

        try:
            gpu_processes_before = self._run_llamacpp_gpu_preflight()
            repetitions = int(profile_config["repetitions"])
            continuous_mode = bool(profile_config.get("continuous"))
            prompt_samples: list[float] = []
            generation_samples: list[float] = []
            prompt_generation_samples: list[float] = []
            final_step_result: dict[str, Any] | None = None
            timeout_per_step = 120 if continuous_mode else max(self.benchmark_timeout_seconds / max(repetitions, 1), 60)

            step = 0
            while True:
                if cancel_event.is_set():
                    break
                if continuous_mode and (time.monotonic() - started_monotonic) >= self.benchmark_timeout_seconds:
                    cancel_event.set()
                    break
                step += 1
                step_run_id = f"{run_id}-step-{step}"
                command = self._build_llamacpp_exec_command(
                    profile_config=profile_config,
                    run_id=step_run_id,
                    repetitions_override=1,
                )
                step_started = time.monotonic()
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                with self._run_state_lock:
                    control = self._active_run_controls.get(run_id)
                    if control is not None:
                        control["process"] = process

                stdout_queue: queue.Queue[str | None] = queue.Queue()
                stderr_queue: queue.Queue[str | None] = queue.Queue()

                def _pump_stream(stream: Any, sink: queue.Queue[str | None]) -> None:
                    try:
                        if stream is None:
                            return
                        for line in iter(stream.readline, ""):
                            sink.put(line)
                    finally:
                        sink.put(None)

                stdout_thread = Thread(target=_pump_stream, args=(process.stdout, stdout_queue), daemon=True)
                stderr_thread = Thread(target=_pump_stream, args=(process.stderr, stderr_queue), daemon=True)
                stdout_thread.start()
                stderr_thread.start()

                timed_out = False
                step_deadline = time.monotonic() + timeout_per_step
                stdout_lines: list[str] = []
                stderr_lines: list[str] = []
                stdout_done = False
                stderr_done = False

                while True:
                    while True:
                        try:
                            line = stdout_queue.get_nowait()
                        except queue.Empty:
                            break
                        if line is None:
                            stdout_done = True
                            break
                        stdout_lines.append(line)
                        if line.startswith("llama-bench:"):
                            self._update_llamacpp_phase_progress(
                                run_id=run_id,
                                started_monotonic=started_monotonic,
                                phase_line=line,
                            )
                        parsed_line = self._parse_llamacpp_jsonl_record(line)
                        if parsed_line is not None:
                            self._update_llamacpp_live_stream_progress(
                                run_id=run_id,
                                started_monotonic=started_monotonic,
                                parsed_line=parsed_line,
                            )

                    while True:
                        try:
                            err_line = stderr_queue.get_nowait()
                        except queue.Empty:
                            break
                        if err_line is None:
                            stderr_done = True
                            break
                        stderr_lines.append(err_line)

                    if process.poll() is not None and stdout_done and stderr_done:
                        break
                    if cancel_event.is_set():
                        self._terminate_process(process)
                        break
                    if time.monotonic() >= step_deadline:
                        timed_out = True
                        self._terminate_process(process)
                        break
                    time.sleep(0.2)

                if cancel_event.is_set():
                    break
                if timed_out:
                    raise LlmInferenceError(504, "llama-bench step timed out")
                stdout_thread.join(timeout=2)
                stderr_thread.join(timeout=2)
                stdout_text = "".join(stdout_lines)
                stderr_text = "".join(stderr_lines)
                if process.returncode != 0:
                    raise LlmInferenceError(
                        502,
                        f"llama-bench failed: {stderr_text.strip() or stdout_text.strip() or f'exit code {process.returncode}'}",
                    )
                jsonl_records: list[dict[str, Any]] = []
                for raw_line in stdout_lines:
                    parsed_line = self._parse_llamacpp_jsonl_record(raw_line)
                    if parsed_line is not None:
                        jsonl_records.append(parsed_line["record"])
                if jsonl_records:
                    parsed_result = self._parse_llamacpp_benchmark_payload({"results": jsonl_records})
                else:
                    try:
                        payload = json.loads(stdout_text)
                    except json.JSONDecodeError as exc:
                        raise LlmInferenceError(502, "llama-bench output did not contain benchmark result records") from exc
                    parsed_result = self._parse_llamacpp_benchmark_payload(payload)
                final_step_result = parsed_result
                if parsed_result.get("prompt_tps_mean") is not None:
                    prompt_samples.append(float(parsed_result["prompt_tps_mean"]))
                if parsed_result.get("generation_tps_mean") is not None:
                    generation_samples.append(float(parsed_result["generation_tps_mean"]))
                if parsed_result.get("prompt_generation_tps_mean") is not None:
                    prompt_generation_samples.append(float(parsed_result["prompt_generation_tps_mean"]))

                self._update_llamacpp_progress(
                    run_id=run_id,
                    step=step,
                    total_steps=0 if continuous_mode else repetitions,
                    step_duration_seconds=max(time.monotonic() - step_started, 0.001),
                    started_monotonic=started_monotonic,
                    parsed_result=parsed_result,
                    prompt_samples=prompt_samples,
                    generation_samples=generation_samples,
                    pg_samples=prompt_generation_samples,
                )

                if not continuous_mode and step >= repetitions:
                    break

            if cancel_event.is_set():
                raise LlmInferenceError(499, "llama.cpp offline benchmark cancelled")

            parsed_result = {
                "prompt_tps_mean": self._llamacpp_mean(prompt_samples),
                "prompt_tps_stddev": self._llamacpp_stddev(prompt_samples),
                "generation_tps_mean": self._llamacpp_mean(generation_samples),
                "generation_tps_stddev": self._llamacpp_stddev(generation_samples),
                "prompt_generation_tps_mean": self._llamacpp_mean(prompt_generation_samples),
                "prompt_generation_tps_stddev": self._llamacpp_stddev(prompt_generation_samples),
                "n_prompt": (final_step_result or {}).get("n_prompt") or profile_config["n_prompt"],
                "n_gen": (final_step_result or {}).get("n_gen") or profile_config["n_gen"],
                "n_depth": (final_step_result or {}).get("n_depth") or profile_config["n_depth"],
                "batch_size": (final_step_result or {}).get("batch_size") or profile_config["batch_size"],
                "ubatch_size": (final_step_result or {}).get("ubatch_size") or profile_config["ubatch_size"],
                "n_gpu_layers": (final_step_result or {}).get("n_gpu_layers") or profile_config["gpu_layers"],
                "repetitions": repetitions,
                "flash_attention": (final_step_result or {}).get("flash_attention") or profile_config["flash_attention"],
            }
            completed_at_ts = int(time.time())
            duration_seconds = max(completed_at_ts - started_at_ts, 0.001)
            result = self._build_llamacpp_result(
                run_id=run_id,
                profile_id=profile_id,
                profile_config=profile_config,
                parsed_result=parsed_result,
                gpu_processes_before=gpu_processes_before,
                started_at_ts=started_at_ts,
                completed_at_ts=completed_at_ts,
                duration_seconds=duration_seconds,
                status="succeeded",
            )
            state = self._read_run_state(run_id)
            state["ts"] = completed_at_ts
            state["status"] = "succeeded"
            state["completed_at_ts"] = completed_at_ts
            if state.get("progress"):
                state["progress"]["elapsed_seconds"] = round(max(time.monotonic() - started_monotonic, 0.0), 3)
            state["result"] = result
            state["error"] = None
            self._write_run_state(run_id, state)
            self._append_history(
                {
                    "ts": completed_at_ts,
                    "event_type": "llamacpp_offline_benchmark",
                    "runtime": self.llamacpp_runtime,
                    "benchmark_mode": self.llamacpp_benchmark_mode,
                    "namespace": self.llamacpp_offline_namespace,
                    "workload": self.llamacpp_offline_target_pod,
                    "status": "succeeded",
                    "run_id": run_id,
                    "profile": str(profile_config["display_name"]),
                    "profile_id": profile_id,
                    "gpu_contended": result["gpu_contended"],
                    "prompt_tps_mean": result["prompt_tps_mean"],
                    "generation_tps_mean": result["generation_tps_mean"],
                    "prompt_generation_tps_mean": result["prompt_generation_tps_mean"],
                    "prompt_tps_stddev": result["prompt_tps_stddev"],
                    "generation_tps_stddev": result["generation_tps_stddev"],
                    "prompt_generation_tps_stddev": result["prompt_generation_tps_stddev"],
                    "duration_seconds": result["duration_seconds"],
                    "observed_at_ts": completed_at_ts,
                }
            )
            with self._run_state_lock:
                self._active_run_controls.pop(run_id, None)
        except Exception as exc:
            status = "cancelled" if cancel_event.is_set() else "failed"
            self._mark_llamacpp_run_failed(
                run_id=run_id,
                profile_id=profile_id,
                profile_config=profile_config,
                started_at_ts=started_at_ts,
                error_summary=None if status == "cancelled" else str(exc),
                gpu_processes_before=gpu_processes_before,
                status=status,
            )

    def start_llamacpp_offline_run(self, *, profile: str) -> dict[str, Any]:
        profile_config = self._resolve_llamacpp_profile(profile)
        with self._run_state_lock:
            for active_run_id, control in self._active_run_controls.items():
                if control.get("kind") == "llamacpp_offline":
                    raise LlmInferenceError(
                        409,
                        f"llama.cpp offline benchmark already running: {active_run_id}",
                    )
        run_id = f"llamacpp-{profile}-run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        state = self._build_llamacpp_run_state(
            run_id=run_id,
            profile_id=profile,
            profile_config=profile_config,
        )
        self._write_run_state(run_id, state)
        cancel_event = Event()
        with self._run_state_lock:
            self._active_run_controls[run_id] = {
                "kind": "llamacpp_offline",
                "cancel_event": cancel_event,
                "process": None,
            }
        thread = Thread(
            target=self._run_llamacpp_offline_background,
            kwargs={"run_id": run_id, "profile_id": profile},
            daemon=True,
        )
        thread.start()
        return {
            "schema": "pre6g.llamacpp_offline_benchmark_run_start.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "runtime": self.llamacpp_runtime,
            "benchmark_mode": self.llamacpp_benchmark_mode,
            "profile": str(profile_config["display_name"]),
            "profile_id": profile,
            "status": "queued",
            "namespace": self.llamacpp_offline_namespace,
            "target_pod": self.llamacpp_offline_target_pod,
        }

    def cancel_llamacpp_offline_run(self, *, run_id: str) -> dict[str, Any]:
        with self._run_state_lock:
            control = self._active_run_controls.get(run_id)
        if control is None:
            state = self._read_run_state(run_id)
            return {
                "schema": "pre6g.llamacpp_offline_benchmark_run_cancel.v1",
                "ts": int(time.time()),
                "run_id": run_id,
                "status": str(state.get("status") or "unknown"),
            }
        cancel_event = control.get("cancel_event")
        if cancel_event is not None:
            cancel_event.set()
        self._terminate_process(control.get("process"))
        state = self._read_run_state(run_id)
        state["status"] = "cancelling"
        state["ts"] = int(time.time())
        self._write_run_state(run_id, state)
        return {
            "schema": "pre6g.llamacpp_offline_benchmark_run_cancel.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "status": "cancelling",
        }

    def get_llamacpp_offline_run(self, *, run_id: str) -> dict[str, Any]:
        state = self._read_run_state(run_id)
        if state.get("runtime") != self.llamacpp_runtime:
            raise KeyError(run_id)
        state["ts"] = int(time.time())
        return state

    def get_llamacpp_offline_latest_run(self) -> dict[str, Any]:
        runs = self.list_llamacpp_offline_runs(limit=1).get("items") or []
        if not runs:
            raise KeyError("latest")
        return runs[0]

    def list_llamacpp_offline_runs(self, *, limit: int = 10) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for run_path in self.runs_root.glob("*.json"):
            try:
                state = json.loads(run_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if state.get("runtime") != self.llamacpp_runtime:
                continue
            items.append(state)
        items.sort(
            key=lambda item: int(
                item.get("completed_at_ts")
                or item.get("started_at_ts")
                or item.get("ts")
                or 0
            ),
            reverse=True,
        )
        trimmed = items[: max(1, min(limit, 50))]
        return {
            "schema": "pre6g.llamacpp_offline_benchmark_runs.v1",
            "ts": int(time.time()),
            "count": len(trimmed),
            "items": trimmed,
        }

    @staticmethod
    def _prometheus_escape_label(value: Any) -> str:
        text = str(value if value is not None else "")
        return text.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

    def _prometheus_metric_line(
        self,
        name: str,
        value: float | int,
        labels: dict[str, Any] | None = None,
    ) -> str:
        if labels:
            encoded = ",".join(
                f'{key}="{self._prometheus_escape_label(raw)}"'
                for key, raw in sorted(labels.items())
            )
            return f"{name}{{{encoded}}} {value}"
        return f"{name} {value}"

    def render_prometheus_metrics(self) -> str:
        now_ts = int(time.time())
        base_labels = {
            "runtime": self.llamacpp_runtime,
            "benchmark_mode": self.llamacpp_benchmark_mode,
            "namespace": self.llamacpp_offline_namespace,
            "target_pod": self.llamacpp_offline_target_pod,
            "node_name": self.llamacpp_offline_node_name,
            "gpu_model": self.llamacpp_gpu_model,
            "gpu_arch": self.llamacpp_gpu_arch,
            "quantization": self.llamacpp_quantization,
        }

        latest_run: dict[str, Any] | None = None
        try:
            latest_run = self.get_llamacpp_offline_latest_run()
        except KeyError:
            latest_run = None

        active_state = None
        if latest_run and latest_run.get("status") in {"queued", "running"}:
            active_state = latest_run

        lines = [
            "# HELP pre6g_llamacpp_offline_benchmark_run_active Whether a llama.cpp offline benchmark run is currently active.",
            "# TYPE pre6g_llamacpp_offline_benchmark_run_active gauge",
            self._prometheus_metric_line(
                "pre6g_llamacpp_offline_benchmark_run_active",
                1 if active_state else 0,
                base_labels,
            ),
            "# HELP pre6g_llamacpp_offline_benchmark_run_status Latest llama.cpp offline benchmark run status as a one-hot gauge.",
            "# TYPE pre6g_llamacpp_offline_benchmark_run_status gauge",
        ]

        latest_status = str((latest_run or {}).get("status") or "none")
        for state_name in ("queued", "running", "succeeded", "failed", "none"):
            labels = dict(base_labels)
            labels["state"] = state_name
            lines.append(
                self._prometheus_metric_line(
                    "pre6g_llamacpp_offline_benchmark_run_status",
                    1 if latest_status == state_name else 0,
                    labels,
                )
            )

        if latest_run:
            profile_id = str(latest_run.get("profile_id") or "")
            run_labels = dict(base_labels)
            if profile_id:
                run_labels["profile_id"] = profile_id

            started_at_ts = latest_run.get("started_at_ts")
            completed_at_ts = latest_run.get("completed_at_ts")
            if started_at_ts is not None:
                lines.extend(
                    [
                        "# HELP pre6g_llamacpp_offline_benchmark_run_started_timestamp_seconds Latest llama.cpp offline benchmark run start timestamp.",
                        "# TYPE pre6g_llamacpp_offline_benchmark_run_started_timestamp_seconds gauge",
                        self._prometheus_metric_line(
                            "pre6g_llamacpp_offline_benchmark_run_started_timestamp_seconds",
                            int(started_at_ts),
                            run_labels,
                        ),
                    ]
                )
            if completed_at_ts is not None:
                lines.extend(
                    [
                        "# HELP pre6g_llamacpp_offline_benchmark_run_completed_timestamp_seconds Latest llama.cpp offline benchmark run completion timestamp.",
                        "# TYPE pre6g_llamacpp_offline_benchmark_run_completed_timestamp_seconds gauge",
                        self._prometheus_metric_line(
                            "pre6g_llamacpp_offline_benchmark_run_completed_timestamp_seconds",
                            int(completed_at_ts),
                            run_labels,
                        ),
                    ]
                )

            if active_state and started_at_ts is not None:
                lines.extend(
                    [
                        "# HELP pre6g_llamacpp_offline_benchmark_run_elapsed_seconds Elapsed runtime of the currently active llama.cpp offline benchmark run.",
                        "# TYPE pre6g_llamacpp_offline_benchmark_run_elapsed_seconds gauge",
                        self._prometheus_metric_line(
                            "pre6g_llamacpp_offline_benchmark_run_elapsed_seconds",
                            max(now_ts - int(started_at_ts), 0),
                            run_labels,
                        ),
                    ]
                )
                progress = active_state.get("progress") or {}
                active_specs: list[tuple[str, str, Any]] = [
                    (
                        "pre6g_llamacpp_offline_benchmark_progress_completed_steps",
                        "Completed repetition steps of the currently active llama.cpp offline benchmark run.",
                        progress.get("completed_steps"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_progress_total_steps",
                        "Total repetition steps configured for the currently active llama.cpp offline benchmark run.",
                        progress.get("total_steps"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_progress_current_prompt_tps",
                        "Current prompt throughput from the latest completed repetition of the active llama.cpp offline benchmark run.",
                        progress.get("current_prompt_tps"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_live_prompt_tps",
                        "Live prompt-only throughput observation for the active llama.cpp offline benchmark run.",
                        progress.get("current_prompt_tps"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_progress_current_generation_tps",
                        "Current generation throughput from the latest completed repetition of the active llama.cpp offline benchmark run.",
                        progress.get("current_generation_tps"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_live_generation_tps",
                        "Live generation-only throughput observation for the active llama.cpp offline benchmark run.",
                        progress.get("current_generation_tps"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_progress_current_prompt_generation_tps",
                        "Current prompt-plus-generation throughput from the latest completed repetition of the active llama.cpp offline benchmark run.",
                        progress.get("current_prompt_generation_tps"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_live_pg_tps",
                        "Live end-to-end PG throughput observation for the active llama.cpp offline benchmark run.",
                        progress.get("current_prompt_generation_tps"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_progress_mean_prompt_tps",
                        "Rolling mean prompt throughput across completed repetitions of the active llama.cpp offline benchmark run.",
                        progress.get("mean_prompt_tps"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_progress_mean_generation_tps",
                        "Rolling mean generation throughput across completed repetitions of the active llama.cpp offline benchmark run.",
                        progress.get("mean_generation_tps"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_progress_mean_prompt_generation_tps",
                        "Rolling mean prompt-plus-generation throughput across completed repetitions of the active llama.cpp offline benchmark run.",
                        progress.get("mean_prompt_generation_tps"),
                    ),
                ]
                for metric_name, help_text, metric_value in active_specs:
                    if metric_value is None:
                        continue
                    lines.append(f"# HELP {metric_name} {help_text}")
                    lines.append(f"# TYPE {metric_name} gauge")
                    lines.append(
                        self._prometheus_metric_line(
                            metric_name,
                            float(metric_value),
                            run_labels,
                        )
                    )

            result = latest_run.get("result") or {}
            if result:
                result_labels = dict(run_labels)
                lines.extend(
                    [
                        "# HELP pre6g_llamacpp_offline_benchmark_result_duration_seconds Duration of the latest completed llama.cpp offline benchmark run.",
                        "# TYPE pre6g_llamacpp_offline_benchmark_result_duration_seconds gauge",
                    ]
                )
                duration_seconds = result.get("duration_seconds")
                if duration_seconds is not None:
                    lines.append(
                        self._prometheus_metric_line(
                            "pre6g_llamacpp_offline_benchmark_result_duration_seconds",
                            float(duration_seconds),
                            result_labels,
                        )
                    )
                if completed_at_ts is not None:
                    lines.extend(
                        [
                            "# HELP pre6g_llamacpp_offline_benchmark_result_freshness_seconds Age of the latest completed llama.cpp offline benchmark result.",
                            "# TYPE pre6g_llamacpp_offline_benchmark_result_freshness_seconds gauge",
                            self._prometheus_metric_line(
                                "pre6g_llamacpp_offline_benchmark_result_freshness_seconds",
                                max(now_ts - int(completed_at_ts), 0),
                                result_labels,
                            ),
                        ]
                    )

                metric_specs: list[tuple[str, str, Any]] = [
                    (
                        "pre6g_llamacpp_offline_benchmark_prompt_tps_mean",
                        "Latest completed llama.cpp offline benchmark prompt processing throughput.",
                        result.get("prompt_tps_mean"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_generation_tps_mean",
                        "Latest completed llama.cpp offline benchmark text generation throughput.",
                        result.get("generation_tps_mean"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_prompt_generation_tps_mean",
                        "Latest completed llama.cpp offline benchmark prompt-plus-generation throughput.",
                        result.get("prompt_generation_tps_mean"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_prompt_tps_stddev",
                        "Latest completed llama.cpp offline benchmark prompt throughput standard deviation.",
                        result.get("prompt_tps_stddev"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_generation_tps_stddev",
                        "Latest completed llama.cpp offline benchmark generation throughput standard deviation.",
                        result.get("generation_tps_stddev"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_prompt_generation_tps_stddev",
                        "Latest completed llama.cpp offline benchmark prompt-plus-generation throughput standard deviation.",
                        result.get("prompt_generation_tps_stddev"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_gpu_preflight_process_count",
                        "GPU process count observed during benchmark preflight.",
                        result.get("gpu_process_count_before"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_gpu_contended",
                        "Whether GPU contention was detected before the latest completed llama.cpp offline benchmark run.",
                        1 if result.get("gpu_contended") else 0,
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_n_prompt",
                        "Prompt token count configured for the latest completed llama.cpp offline benchmark run.",
                        result.get("n_prompt"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_n_gen",
                        "Generation token count configured for the latest completed llama.cpp offline benchmark run.",
                        result.get("n_gen"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_n_depth",
                        "Context depth configured for the latest completed llama.cpp offline benchmark run.",
                        result.get("n_depth"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_batch_size",
                        "Batch size configured for the latest completed llama.cpp offline benchmark run.",
                        result.get("batch_size"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_ubatch_size",
                        "Micro-batch size configured for the latest completed llama.cpp offline benchmark run.",
                        result.get("ubatch_size"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_n_gpu_layers",
                        "Number of GPU layers configured for the latest completed llama.cpp offline benchmark run.",
                        result.get("n_gpu_layers"),
                    ),
                    (
                        "pre6g_llamacpp_offline_benchmark_repetitions",
                        "Repetitions configured for the latest completed llama.cpp offline benchmark run.",
                        result.get("repetitions"),
                    ),
                ]
                for metric_name, help_text, metric_value in metric_specs:
                    if metric_value is None:
                        continue
                    lines.append(f"# HELP {metric_name} {help_text}")
                    lines.append(f"# TYPE {metric_name} gauge")
                    lines.append(
                        self._prometheus_metric_line(
                            metric_name,
                            float(metric_value),
                            result_labels,
                        )
                    )

        return "\n".join(lines) + "\n"

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
