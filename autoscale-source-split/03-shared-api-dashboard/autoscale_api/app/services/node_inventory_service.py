import time
from typing import Any, Dict, List, Optional

from app.adapters.gpu_static_map_adapter import GPUStaticMapAdapter
from app.adapters.inventory_extra_adapter import InventoryExtraAdapter
from app.adapters.k8s_adapter import K8sAdapter
from app.schemas.node import (
    CPUCacheInfo,
    NodeCPUInfo,
    NodeGPUInfo,
    NodeInventory,
    NodeListResponse,
    NodeMemoryInfo,
    NodeOSInfo,
)
from app.services.cache_service import SimpleTTLCache


def get_address(addresses: List[Dict[str, Any]], addr_type: str) -> str:
    for addr in addresses:
        if addr.get("type") == addr_type:
            return addr.get("address", "")
    return ""


def get_role(labels: Dict[str, str]) -> str:
    if "node-role.kubernetes.io/control-plane" in labels:
        return "control-plane"
    if "node-role.kubernetes.io/master" in labels:
        return "control-plane"
    return "worker"


def build_compute_capability(labels: Dict[str, str]) -> Optional[str]:
    major = labels.get("nvidia.com/gpu.compute.major")
    minor = labels.get("nvidia.com/gpu.compute.minor")
    if major is None or minor is None:
        return None
    return f"{major}.{minor}"


def ki_to_mib_str(mem_ki: str) -> str:
    if mem_ki.endswith("Ki"):
        mib = int(mem_ki[:-2]) // 1024
        return f"{mib} MiB"
    return mem_ki


class NodeInventoryService:
    def __init__(self, cache: SimpleTTLCache | None = None) -> None:
        self.k8s = K8sAdapter()
        self.extra = InventoryExtraAdapter()
        self.gpu_map = GPUStaticMapAdapter()
        self.cache = cache or SimpleTTLCache()

    def build_node_inventory(self, raw_node: Dict[str, Any]) -> NodeInventory:
        metadata = raw_node.get("metadata", {})
        status = raw_node.get("status", {})

        labels = metadata.get("labels", {})
        addresses = status.get("addresses", [])
        node_info = status.get("node_info", {})
        capacity = status.get("capacity", {})

        node_name = metadata.get("name", "")
        role = get_role(labels)
        k8s_ip = get_address(addresses, "InternalIP")

        extra_data = self.extra.get_node_extra(node_name)
        extra_cpu = extra_data.get("cpu", {})
        extra_mem = extra_data.get("memory", {})

        gpu_count = int(capacity.get("nvidia.com/gpu", "0"))
        gpu_model = labels.get("nvidia.com/gpu.product")
        gpu_models = [gpu_model] if gpu_model else []

        gpu_memory_mb = labels.get("nvidia.com/gpu.memory")
        gpu_memory_str = f"{gpu_memory_mb} MiB" if gpu_memory_mb else None

        return NodeInventory(
            node_name=node_name,
            role=role,
            k8s_ip=k8s_ip,
            os=NodeOSInfo(
                image=node_info.get("os_image", ""),
                kernel_version=node_info.get("kernel_version", ""),
                container_runtime=node_info.get("container_runtime_version", ""),
            ),
            cpu=NodeCPUInfo(
                model_name=extra_cpu.get("model_name"),
                vendor=labels.get("feature.node.kubernetes.io/cpu-model.vendor_id"),
                family=labels.get("feature.node.kubernetes.io/cpu-model.family"),
                model_id=labels.get("feature.node.kubernetes.io/cpu-model.id"),
                cores_total=int(capacity.get("cpu", "0")),
                base_clock_ghz=extra_cpu.get("base_clock_ghz"),
                max_clock_ghz=extra_cpu.get("max_clock_ghz"),
                cache=CPUCacheInfo(
                    l1d=extra_cpu.get("cache", {}).get("l1d"),
                    l1i=extra_cpu.get("cache", {}).get("l1i"),
                    l2=extra_cpu.get("cache", {}).get("l2"),
                    l3=extra_cpu.get("cache", {}).get("l3"),
                ),
            ),
            memory=NodeMemoryInfo(
                total_memory=ki_to_mib_str(capacity.get("memory", "0")),
                ddr_gen=extra_mem.get("ddr_gen"),
                frequency_mt_s=extra_mem.get("frequency_mt_s"),
                cas_latency=extra_mem.get("cas_latency"),
            ),
            gpu=NodeGPUInfo(
                has_gpu=gpu_count > 0,
                count=gpu_count,
                models=gpu_models,
                family=labels.get("nvidia.com/gpu.family"),
                memory=gpu_memory_str,
                compute_capability=build_compute_capability(labels),
                cuda_driver_version=labels.get("nvidia.com/cuda.driver-version.full"),
                cuda_cores=self.gpu_map.get_cuda_cores(gpu_model),
            ),
            query_enabled=True,
        )

    def get_node_list(self) -> NodeListResponse:
        cache_key = "node_list_v1"
        cached = self.cache.get(cache_key, ttl_seconds=60)
        if cached is not None:
            return cached

        print("Refreshing node_list cache from Kubernetes API")
        raw_nodes = self.k8s.list_nodes_raw()
        nodes = [self.build_node_inventory(node) for node in raw_nodes]

        response = NodeListResponse(
            schema="pre6g.node_list.v1",
            ts=int(time.time()),
            count=len(nodes),
            nodes=nodes,
        )
        self.cache.set(cache_key, response)
        return response
