import os
import time
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    SHORT_PROMPT = "Explain CPU RAM and GPU VRAM in three short bullet points."
    MEDIUM_PROMPT = (
        "Summarize how CPU RAM, GPU VRAM, and storage differ for AI workloads. "
        "Include one practical example for inference serving."
    )
    LONG_CONTEXT_PROMPT = (
        "You are given a repeated systems note. Summarize the main bottlenecks for LLM serving.\n\n"
        + ("CPU schedules data movement. GPU VRAM stores model weights and KV cache. "
           "Long context increases prompt processing cost and KV cache pressure. " * 80)
    )
    BENCHMARK_PROFILES: dict[str, dict[str, Any]] = {
        "smoke": {
            "display_name": "Smoke",
            "prompt": SHORT_PROMPT,
            "max_tokens": 64,
            "temperature": 0.0,
            "concurrency": 1,
            "request_count": 20,
            "description": "Minimal fixed profile for control-path and TPS visibility checks.",
        },
        "steady": {
            "display_name": "Steady",
            "prompt": MEDIUM_PROMPT,
            "max_tokens": 128,
            "temperature": 0.0,
            "concurrency": 4,
            "request_count": 30,
            "description": "Medium prompt/output profile with closed-loop concurrent workers.",
        },
        "long-context": {
            "display_name": "Long Context",
            "prompt": LONG_CONTEXT_PROMPT,
            "max_tokens": 64,
            "temperature": 0.0,
            "concurrency": 2,
            "request_count": 8,
            "description": "Long prompt profile with limited concurrency to exercise context pressure.",
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
        self._active_run_controls: dict[str, Event] = {}

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

        service_url, model_name = self._resolve_ready_target(namespace=namespace, workload=workload)
        run_id = f"{profile}-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        completed = 0
        failed = 0
        started = time.time()
        latencies: list[Optional[float]] = []
        prompt_tokens: list[Optional[float]] = []
        completion_tokens: list[Optional[float]] = []
        total_tokens: list[Optional[float]] = []
        first_error: LlmInferenceError | None = None
        request_count = int(profile_config["request_count"])
        concurrency = max(1, int(profile_config["concurrency"]))
        prompt = str(profile_config["prompt"])
        max_tokens = int(profile_config["max_tokens"])
        temperature = float(profile_config["temperature"])

        def worker(_: int) -> dict[str, Any]:
            return self._execute_inference_request(
                service_url=service_url,
                model_name=model_name,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(worker, index) for index in range(request_count)]
            for future in as_completed(futures):
                try:
                    result = future.result()
                    completed += 1
                    latencies.append(result.get("latency_seconds"))
                    prompt_tokens.append(result.get("prompt_tokens"))
                    completion_tokens.append(result.get("completion_tokens"))
                    total_tokens.append(result.get("total_tokens"))
                except LlmInferenceError as exc:
                    failed += 1
                    if first_error is None:
                        first_error = exc

        if completed == 0 and first_error is not None:
            raise first_error
        result = self._finalize_run_result(
            namespace=namespace,
            workload=workload,
            profile=profile,
            profile_config=profile_config,
            run_id=run_id,
            completed=completed,
            failed=failed,
            started_monotonic=started,
            latencies=latencies,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        self._append_history(
            {
                "ts": result["ts"],
                "event_type": "controlled_batch",
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
            self._active_run_controls[run_id] = cancel_event

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

        completed = 0
        failed = 0
        latencies: list[Optional[float]] = []
        prompt_tokens: list[Optional[float]] = []
        completion_tokens: list[Optional[float]] = []
        total_tokens: list[Optional[float]] = []
        first_error: LlmInferenceError | None = None

        try:
            service_url, model_name = self._resolve_ready_target(namespace=namespace, workload=workload)
            request_count = int(profile_config["request_count"])
            concurrency = max(1, int(profile_config["concurrency"]))
            prompt = str(profile_config["prompt"])
            max_tokens = int(profile_config["max_tokens"])
            temperature = float(profile_config["temperature"])

            def worker(_: int) -> dict[str, Any]:
                if cancel_event.is_set():
                    raise LlmInferenceError(499, "benchmark run cancelled")
                return self._execute_inference_request(
                    service_url=service_url,
                    model_name=model_name,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(worker, index) for index in range(request_count)]
                for future in as_completed(futures):
                    state = self._read_run_state(run_id)
                    if cancel_event.is_set():
                        state["status"] = "cancelled"
                        state["finished_ts"] = int(time.time())
                        self._update_run_progress(state=state, started_monotonic=started)
                        self._write_run_state(run_id, state)
                        return
                    try:
                        result = future.result()
                        completed += 1
                        prompt_value = float(result.get("prompt_tokens") or 0.0)
                        completion_value = float(result.get("completion_tokens") or 0.0)
                        total_value = float(result.get("total_tokens") or (prompt_value + completion_value))
                        latencies.append(result.get("latency_seconds"))
                        prompt_tokens.append(result.get("prompt_tokens"))
                        completion_tokens.append(result.get("completion_tokens"))
                        total_tokens.append(result.get("total_tokens"))
                        self._update_run_progress(
                            state=state,
                            started_monotonic=started,
                            completed_delta=1,
                            prompt_tokens_delta=prompt_value,
                            completion_tokens_delta=completion_value,
                            total_tokens_delta=total_value,
                        )
                    except LlmInferenceError as exc:
                        failed += 1
                        if first_error is None and exc.status_code != 499:
                            first_error = exc
                        self._update_run_progress(
                            state=state,
                            started_monotonic=started,
                            failed_delta=1,
                        )
                    state["ts"] = int(time.time())
                    self._write_run_state(run_id, state)
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

        if completed == 0 and first_error is not None:
            state = self._read_run_state(run_id)
            state["status"] = "failed"
            state["finished_ts"] = int(time.time())
            state["error"] = first_error.detail
            self._update_run_progress(state=state, started_monotonic=started)
            self._write_run_state(run_id, state)
            with self._run_state_lock:
                self._active_run_controls.pop(run_id, None)
            return

        result = self._finalize_run_result(
            namespace=namespace,
            workload=workload,
            profile=profile,
            profile_config=profile_config,
            run_id=run_id,
            completed=completed,
            failed=failed,
            started_monotonic=started,
            latencies=latencies,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        state = self._read_run_state(run_id)
        state["status"] = result["status"]
        state["finished_ts"] = int(time.time())
        state["result"] = result
        state["error"] = None
        self._update_run_progress(state=state, started_monotonic=started)
        state["ts"] = int(time.time())
        self._write_run_state(run_id, state)
        self._append_history(
            {
                "ts": result["ts"],
                "event_type": "controlled_batch",
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
            cancel_event = self._active_run_controls.get(run_id)
        if cancel_event is None:
            state = self._read_run_state(run_id)
            return {
                "schema": "pre6g.llm_benchmark_run_cancel.v1",
                "ts": int(time.time()),
                "run_id": run_id,
                "status": str(state.get("status") or "unknown"),
            }
        cancel_event.set()
        return {
            "schema": "pre6g.llm_benchmark_run_cancel.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "status": "cancelling",
        }

    def run_smoke_benchmark(self, *, namespace: str, workload: str) -> dict[str, Any]:
        return self.run_benchmark_profile(namespace=namespace, workload=workload, profile="smoke")

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
