import sys
import time
from pathlib import Path

from app.schemas.node import (
    NodeStatus,
    NodeStatusCPU,
    NodeStatusDisk,
    NodeStatusGPU,
    NodeStatusListResponse,
    NodeStatusMemory,
    NodeStatusResponse,
    NodeStatusSources,
)
from app.services.cache_service import SimpleTTLCache
from app.services.node_inventory_service import NodeInventoryService

# Let this source-split API import ../01-monitoring-layer/vm_aggregator.py.
SOURCE_SPLIT_ROOT = Path(__file__).resolve().parents[4]
MONITORING_LAYER = SOURCE_SPLIT_ROOT / "01-monitoring-layer"
if MONITORING_LAYER.exists() and str(MONITORING_LAYER) not in sys.path:
    sys.path.append(str(MONITORING_LAYER))

import vm_aggregator  # noqa: E402


def bytes_to_mib(n: int) -> int:
    return round(n / (1024 * 1024))


class NodeStatusService:
    def __init__(self, cache: SimpleTTLCache | None = None) -> None:
        self.cache = cache or SimpleTTLCache()
        self.inventory_service = NodeInventoryService(cache=self.cache)

    def _get_k8s_ip_map(self) -> dict[str, str]:
        node_list = self.inventory_service.get_node_list()
        return {n.node_name: n.k8s_ip for n in node_list.nodes}

    def _map_raw_state_to_node_status(self, raw: dict) -> NodeStatus:
        meta = raw.get("meta", {})
        target = raw.get("target_node_semantic", {})

        node_name = meta.get("target_host", "")
        k8s_ip_map = self._get_k8s_ip_map()
        k8s_ip = k8s_ip_map.get(node_name, "")

        node_pressure = target.get("node_pressure", {})
        node_pressure_instant = target.get("node_pressure_instant", {})
        gpu_pressure = target.get("gpu_pressure", {})

        cpu_usage_percent = node_pressure_instant.get("cpu_usage_percent")
        if cpu_usage_percent is None:
            cpu_usage_percent = node_pressure.get("cpu_usage_percent")

        memory_usage_percent = node_pressure_instant.get("memory_usage_percent")
        if memory_usage_percent is None:
            memory_usage_percent = node_pressure.get("memory_usage_percent")

        working_set_bytes = int(node_pressure_instant.get("node_memory_working_set_bytes") or 0)

        return NodeStatus(
            node_name=node_name,
            k8s_ip=k8s_ip,
            sources=NodeStatusSources(
                node_metrics="vm+netdata",
                gpu_metrics="dcgm_exporter+k8s",
            ),
            cpu=NodeStatusCPU(
                usage_percent=float(cpu_usage_percent or 0.0),
                used_cores=float(node_pressure_instant.get("node_cpu_cores") or 0.0),
            ),
            memory=NodeStatusMemory(
                usage_percent=float(memory_usage_percent or 0.0),
                working_set_bytes=working_set_bytes,
                working_set_mib=bytes_to_mib(working_set_bytes),
            ),
            disk=NodeStatusDisk(
                root_usage_percent=float(node_pressure.get("disk_root_usage_percent") or 0.0),
            ),
            gpu=NodeStatusGPU(
                status=str(gpu_pressure.get("status") or "unknown"),
                count=int(gpu_pressure.get("gpu_count") or 0),
                fb_used_bytes=int(gpu_pressure.get("fb_used_total_bytes") or 0),
                fb_used_mib=float(gpu_pressure.get("fb_used_total_mib") or 0.0),
            ),
        )

    def get_node_status(self, node_name: str) -> NodeStatusResponse:
        cache_key = f"node_status::{node_name}"
        cached = self.cache.get(cache_key, ttl_seconds=5)
        if cached is not None:
            return cached

        raw = vm_aggregator.collect_state_for_node(node_name)
        node = self._map_raw_state_to_node_status(raw)

        response = NodeStatusResponse(
            schema="pre6g.node_status.v1",
            ts=int(time.time()),
            node=node,
        )
        self.cache.set(cache_key, response)
        return response

    def get_all_node_status(self) -> NodeStatusListResponse:
        cache_key = "node_status::all"
        cached = self.cache.get(cache_key, ttl_seconds=5)
        if cached is not None:
            return cached

        node_list = self.inventory_service.get_node_list()
        nodes = []

        for inv in node_list.nodes:
            try:
                raw = vm_aggregator.collect_state_for_node(inv.node_name)
                nodes.append(self._map_raw_state_to_node_status(raw))
            except Exception as e:
                print(f"[node_status] failed to collect node={inv.node_name}: {e}", flush=True)

                nodes.append(
                    NodeStatus(
                        node_name=inv.node_name,
                        k8s_ip=inv.k8s_ip,
                        sources=NodeStatusSources(
                            node_metrics="error",
                            gpu_metrics="error",
                        ),
                        cpu=NodeStatusCPU(
                            usage_percent=0.0,
                            used_cores=0.0,
                        ),
                        memory=NodeStatusMemory(
                            usage_percent=0.0,
                            working_set_bytes=0,
                            working_set_mib=0,
                        ),
                        disk=NodeStatusDisk(
                            root_usage_percent=0.0,
                        ),
                        gpu=NodeStatusGPU(
                            status=f"metrics_error: {str(e)[:120]}",
                            count=0,
                            fb_used_bytes=0,
                            fb_used_mib=0.0,
                        ),
                    )
                )

        response = NodeStatusListResponse(
            schema="pre6g.node_status.v1",
            ts=int(time.time()),
            count=len(nodes),
            nodes=nodes,
        )
        self.cache.set(cache_key, response)
        return response
