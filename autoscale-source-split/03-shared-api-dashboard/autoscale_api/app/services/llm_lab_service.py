import os
import time
import json
from datetime import datetime, timezone
from pathlib import Path
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
            "concurrency": 1,
            "request_count": 30,
            "description": "Medium prompt/output profile for short steady-state observation.",
        },
        "long-context": {
            "display_name": "Long Context",
            "prompt": LONG_CONTEXT_PROMPT,
            "max_tokens": 64,
            "temperature": 0.0,
            "concurrency": 1,
            "request_count": 8,
            "description": "Long prompt profile to exercise prompt TPS and context pressure.",
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
        workload_status = self.workloads.get_workload_status(namespace=namespace, workload=workload)
        if workload_status.replica_summary.ready <= 0:
            raise LlmInferenceError(409, f"workload is not ready: {namespace}/{workload}")

        service_url = self._resolve_service_url(namespace=namespace, workload=workload)
        model_name = (
            workload_status.identity.served_model_id
            or workload_status.identity.model_name
            or workload_status.identity.workload
        )

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
            "schema": "pre6g.llm_inference.v1",
            "ts": int(time.time()),
            "namespace": namespace,
            "workload": workload,
            "target_url": service_url,
            "model": model_name,
            "http_status": response.status_code,
            "latency_seconds": latency_seconds,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "finish_reason": self._extract_finish_reason(response_payload),
            "response_text": self._extract_response_text(response_payload),
        }
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
                    "prompt_tokens": result["prompt_tokens"],
                    "completion_tokens": result["completion_tokens"],
                    "total_tokens": result["total_tokens"],
                    "finish_reason": result["finish_reason"],
                    "prompt_preview": prompt[:160],
                }
            )
        return result

    @staticmethod
    def _mean(values: list[Optional[float]]) -> Optional[float]:
        filtered = [float(value) for value in values if value is not None]
        if not filtered:
            return None
        return round(sum(filtered) / len(filtered), 3)

    def run_benchmark_profile(self, *, namespace: str, workload: str, profile: str) -> dict[str, Any]:
        profile_config = self.BENCHMARK_PROFILES.get(profile)
        if not profile_config:
            raise LlmInferenceError(404, f"unknown benchmark profile: {profile}")

        run_id = f"{profile}-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        completed = 0
        failed = 0
        latencies: list[Optional[float]] = []
        prompt_tokens: list[Optional[float]] = []
        completion_tokens: list[Optional[float]] = []
        total_tokens: list[Optional[float]] = []

        for _ in range(int(profile_config["request_count"])):
            try:
                result = self.run_inference(
                    namespace=namespace,
                    workload=workload,
                    prompt=str(profile_config["prompt"]),
                    max_tokens=int(profile_config["max_tokens"]),
                    temperature=float(profile_config["temperature"]),
                    record_history=False,
                )
                completed += 1
                latencies.append(result.get("latency_seconds"))
                prompt_tokens.append(result.get("prompt_tokens"))
                completion_tokens.append(result.get("completion_tokens"))
                total_tokens.append(result.get("total_tokens"))
            except LlmInferenceError as exc:
                failed += 1
                if completed == 0:
                    raise exc

        result = {
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
            "mean_latency_seconds": self._mean(latencies),
            "mean_prompt_tokens": self._mean(prompt_tokens),
            "mean_completion_tokens": self._mean(completion_tokens),
            "mean_total_tokens": self._mean(total_tokens),
        }
        self._append_history(
            {
                "ts": result["ts"],
                "event_type": "smoke_benchmark",
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
                "mean_latency_seconds": result["mean_latency_seconds"],
                "mean_prompt_tokens": result["mean_prompt_tokens"],
                "mean_completion_tokens": result["mean_completion_tokens"],
                "mean_total_tokens": result["mean_total_tokens"],
            }
        )
        return result

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
