import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, Optional


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _first_non_empty(labels: dict, candidates: Iterable[str]) -> Optional[str]:
    for key in candidates:
        value = str(labels.get(key) or "").strip()
        if value:
            return value
    return None


@dataclass
class ReplicaMetricSnapshot:
    pod: str
    namespace: str
    node_name: str
    ts: int
    model_name: Optional[str] = None
    served_model_id: Optional[str] = None
    runtime_version: Optional[str] = None
    generation_tokens_per_second: Optional[float] = None
    prompt_tokens_per_second: Optional[float] = None
    waiting_requests: Optional[float] = None
    kv_cache_usage_percent: Optional[float] = None

    def has_any_metric(self) -> bool:
        return any(
            value is not None
            for value in (
                self.generation_tokens_per_second,
                self.prompt_tokens_per_second,
                self.waiting_requests,
                self.kv_cache_usage_percent,
            )
        )


class VllmWorkloadAdapter:
    GENERATION_TOKEN_METRICS = (
        "vllm:generation_tokens_total",
        "vllm:generated_tokens_total",
    )
    PROMPT_TOKEN_METRICS = (
        "vllm:prompt_tokens_total",
        "vllm:prefill_tokens_total",
    )
    WAITING_REQUEST_METRICS = (
        "vllm:num_requests_waiting",
        "vllm:waiting_requests",
    )
    KV_CACHE_USAGE_METRICS = (
        "vllm:gpu_cache_usage_perc",
        "vllm:kv_cache_usage_perc",
    )
    INFO_METRICS = (
        "vllm:info",
        "vllm:build_info",
    )
    GROUP_LABELS = (
        "kubernetes_namespace",
        "kubernetes_pod",
        "kubernetes_node",
        "model_name",
        "served_model_name",
        "served_model_id",
        "model",
        "version",
        "runtime_version",
    )

    def __init__(
        self,
        vm_url: str | None = None,
        query_window_seconds: int | None = None,
    ) -> None:
        self.vm_url = (vm_url or os.getenv("VM_URL", "http://140.113.179.9:31888")).rstrip("/")
        env_window = os.getenv("PRE6G_WORKLOAD_QUERY_WINDOW_SECONDS", "").strip()
        if query_window_seconds is not None:
            self.query_window_seconds = int(query_window_seconds)
        elif env_window:
            self.query_window_seconds = max(5, int(env_window))
        else:
            self.query_window_seconds = 60

    def _vm_query(self, promql: str) -> list[dict]:
        url = f"{self.vm_url}/api/v1/query?" + urllib.parse.urlencode({"query": promql})
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            payload = resp.read().decode("utf-8", errors="replace")

        import json

        data = json.loads(payload)
        if data.get("status") != "success":
            raise RuntimeError(f"victoriametrics query failed: {data}")
        return list(data.get("data", {}).get("result") or [])

    def _series_selector(self, metric_name: str, namespace: str) -> str:
        return f'{metric_name}{{kubernetes_namespace={_quote(namespace)}}}'

    def _query_metric_vector(
        self,
        metric_candidates: Iterable[str],
        namespace: str,
        mode: str,
    ) -> tuple[Optional[str], list[dict]]:
        group = ", ".join(self.GROUP_LABELS)
        for metric_name in metric_candidates:
            selector = self._series_selector(metric_name, namespace)
            if mode == "rate":
                promql = (
                    f"sum by ({group}) (rate({selector}[{self.query_window_seconds}s]))"
                )
            else:
                promql = f"max by ({group}) ({selector})"

            result = self._vm_query(promql)
            if result:
                return metric_name, result
        return None, []

    def collect_namespace_metrics(self, namespace: str) -> dict[str, ReplicaMetricSnapshot]:
        snapshots: Dict[str, ReplicaMetricSnapshot] = {}
        now = int(time.time())

        def ensure_snapshot(metric_labels: dict, ts: int) -> Optional[ReplicaMetricSnapshot]:
            pod = _first_non_empty(metric_labels, ("kubernetes_pod", "pod"))
            ns = _first_non_empty(metric_labels, ("kubernetes_namespace", "namespace")) or namespace
            if not pod:
                return None

            node_name = _first_non_empty(metric_labels, ("kubernetes_node", "node")) or ""
            snapshot = snapshots.get(pod)
            if snapshot is None:
                snapshot = ReplicaMetricSnapshot(
                    pod=pod,
                    namespace=ns,
                    node_name=node_name,
                    ts=ts,
                )
                snapshots[pod] = snapshot

            snapshot.node_name = snapshot.node_name or node_name
            snapshot.ts = max(snapshot.ts, ts)
            snapshot.model_name = snapshot.model_name or _first_non_empty(
                metric_labels,
                ("model_name", "served_model_name", "model"),
            )
            snapshot.served_model_id = snapshot.served_model_id or _first_non_empty(
                metric_labels,
                ("served_model_id", "served_model_name", "model_name", "model"),
            )
            snapshot.runtime_version = snapshot.runtime_version or _first_non_empty(
                metric_labels,
                ("runtime_version", "version"),
            )
            return snapshot

        def apply(metric_candidates: Iterable[str], mode: str, field_name: str) -> None:
            _, result = self._query_metric_vector(metric_candidates, namespace=namespace, mode=mode)
            for item in result:
                labels = item.get("metric") or {}
                value = item.get("value") or []
                if len(value) != 2:
                    continue
                ts = int(float(value[0]))
                raw_value = float(value[1])
                snapshot = ensure_snapshot(labels, ts)
                if snapshot is None:
                    continue

                if field_name == "kv_cache_usage_percent" and 0.0 <= raw_value <= 1.0:
                    raw_value *= 100.0
                setattr(snapshot, field_name, raw_value)

        apply(self.GENERATION_TOKEN_METRICS, mode="rate", field_name="generation_tokens_per_second")
        apply(self.PROMPT_TOKEN_METRICS, mode="rate", field_name="prompt_tokens_per_second")
        apply(self.WAITING_REQUEST_METRICS, mode="gauge", field_name="waiting_requests")
        apply(self.KV_CACHE_USAGE_METRICS, mode="gauge", field_name="kv_cache_usage_percent")

        # Best-effort runtime version/model identity enrichment.
        _, info_result = self._query_metric_vector(self.INFO_METRICS, namespace=namespace, mode="gauge")
        for item in info_result:
            labels = item.get("metric") or {}
            value = item.get("value") or []
            if len(value) != 2:
                continue
            snapshot = ensure_snapshot(labels, int(float(value[0])))
            if snapshot is None:
                continue
            snapshot.runtime_version = snapshot.runtime_version or _first_non_empty(
                labels,
                ("version", "runtime_version"),
            )
            snapshot.model_name = snapshot.model_name or _first_non_empty(
                labels,
                ("model_name", "served_model_name", "model"),
            )
            snapshot.served_model_id = snapshot.served_model_id or _first_non_empty(
                labels,
                ("served_model_id", "served_model_name", "model_name"),
            )

        for snapshot in snapshots.values():
            if snapshot.ts <= 0:
                snapshot.ts = now
        return snapshots
