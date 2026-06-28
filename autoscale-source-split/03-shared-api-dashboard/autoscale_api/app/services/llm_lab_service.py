import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from app.adapters.k8s_adapter import K8sAdapter
from app.services.workload_status_service import WorkloadStatusService


class LlmInferenceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class LlmLabService:
    SMOKE_PROMPT = (
        "Explain CPU RAM and GPU VRAM in three short bullet points."
    )
    SMOKE_MAX_TOKENS = 64
    SMOKE_TEMPERATURE = 0.0
    SMOKE_REQUEST_COUNT = 20

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
        return {
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

    @staticmethod
    def _mean(values: list[Optional[float]]) -> Optional[float]:
        filtered = [float(value) for value in values if value is not None]
        if not filtered:
            return None
        return round(sum(filtered) / len(filtered), 3)

    def run_smoke_benchmark(self, *, namespace: str, workload: str) -> dict[str, Any]:
        run_id = "smoke-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        completed = 0
        failed = 0
        latencies: list[Optional[float]] = []
        prompt_tokens: list[Optional[float]] = []
        completion_tokens: list[Optional[float]] = []
        total_tokens: list[Optional[float]] = []

        for _ in range(self.SMOKE_REQUEST_COUNT):
            try:
                result = self.run_inference(
                    namespace=namespace,
                    workload=workload,
                    prompt=self.SMOKE_PROMPT,
                    max_tokens=self.SMOKE_MAX_TOKENS,
                    temperature=self.SMOKE_TEMPERATURE,
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

        return {
            "schema": "pre6g.llm_smoke_benchmark.v1",
            "ts": int(time.time()),
            "run_id": run_id,
            "namespace": namespace,
            "workload": workload,
            "profile": "Smoke",
            "request_count": self.SMOKE_REQUEST_COUNT,
            "max_tokens": self.SMOKE_MAX_TOKENS,
            "temperature": self.SMOKE_TEMPERATURE,
            "status": "succeeded" if failed == 0 else "completed_with_errors",
            "completed_requests": completed,
            "failed_requests": failed,
            "mean_latency_seconds": self._mean(latencies),
            "mean_prompt_tokens": self._mean(prompt_tokens),
            "mean_completion_tokens": self._mean(completion_tokens),
            "mean_total_tokens": self._mean(total_tokens),
        }
