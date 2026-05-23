import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

from app.schemas.full_metrics import (
    FullMetricsListResponse,
    FullMetricsNodePayload,
    FullMetricsResponse,
)
from app.services.cache_service import SimpleTTLCache

AUTOSCALE_ROOT = Path(__file__).resolve().parents[3]


class FullMetricsService:
    def __init__(self, cache: SimpleTTLCache | None = None) -> None:
        self.cache = cache or SimpleTTLCache()
        self.max_workers = max(1, int(os.getenv("FULL_METRICS_MAX_WORKERS", "8")))

    def _load_nodes(self) -> List[Dict[str, Any]]:
        from collect_node_metrics_csv import load_nodes  # local import to keep startup light

        return load_nodes()

    def _run_aggregator(self, node: Dict[str, Any]) -> Dict[str, Any]:
        from collect_node_metrics_csv import run_aggregator  # local import to keep startup light

        try:
            return run_aggregator(node)
        except Exception as exc:
            return {
                "collector_status": "error",
                "collector_error": str(exc),
            }

    def _collect_node_payload(self, node: Dict[str, Any]) -> FullMetricsNodePayload:
        payload = self._run_aggregator(node)
        return FullMetricsNodePayload(
            node_name=node["node_name"],
            node_type=node["node_type"],
            aggregator=node["aggregator"],
            payload=payload,
        )

    def _collect_all(self) -> List[FullMetricsNodePayload]:
        nodes = self._load_nodes()
        if not nodes:
            return []

        max_workers = min(self.max_workers, len(nodes))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(self._collect_node_payload, nodes))

    def get_all_metrics(self) -> FullMetricsListResponse:
        cache_key = "full_metrics::all"
        cached = self.cache.get(cache_key, ttl_seconds=5)
        if cached is not None:
            return cached

        nodes = self._collect_all()
        ok_count = sum(1 for node in nodes if node.payload.get("collector_status") == "ok")
        response = FullMetricsListResponse(
            schema="pre6g.full_metrics_list.v1",
            ts=int(time.time()),
            count=len(nodes),
            ok_count=ok_count,
            error_count=len(nodes) - ok_count,
            nodes=nodes,
        )
        self.cache.set(cache_key, response)
        return response

    def get_node_metrics(self, node_name: str) -> FullMetricsResponse:
        cache_key = f"full_metrics::{node_name}"
        cached = self.cache.get(cache_key, ttl_seconds=5)
        if cached is not None:
            return cached

        for node in self._load_nodes():
            if node["node_name"] != node_name:
                continue

            response = FullMetricsResponse(
                schema="pre6g.full_metrics.v1",
                ts=int(time.time()),
                node=FullMetricsNodePayload(
                    node_name=node["node_name"],
                    node_type=node["node_type"],
                    aggregator=node["aggregator"],
                    payload=self._run_aggregator(node),
                ),
            )
            self.cache.set(cache_key, response)
            return response

        raise KeyError(f"unknown node: {node_name}")
