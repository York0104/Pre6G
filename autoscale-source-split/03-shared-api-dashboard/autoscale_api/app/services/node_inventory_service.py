import json
import sys
import time
from pathlib import Path
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

SOURCE_SPLIT_ROOT = Path(__file__).resolve().parents[4]
MONITORING_LAYER = SOURCE_SPLIT_ROOT / "01-monitoring-layer"
COLLECTOR_NODES_PATH = MONITORING_LAYER / "collector_nodes.json"

if MONITORING_LAYER.exists() and str(MONITORING_LAYER) not in sys.path:
    sys.path.append(str(MONITORING_LAYER))

import vm_aggregator  # noqa: E402


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

    def _infer_gpu_models_from_aggregator(self, node_name: str) -> List[str]:
        cache_key = f"node_gpu_models::{node_name}"
        cached = self.cache.get(cache_key, ttl_seconds=30)
        if cached is not None:
            return cached

        try:
            raw = vm_aggregator.collect_state_for_node(node_name)
            target = raw.get("target_node_semantic", {})
            gpu_pressure = target.get("gpu_pressure", {})
            gpu_entries = gpu_pressure.get("gpus") or gpu_pressure.get("gpu_list") or []
            models = []
            for gpu in gpu_entries:
                if not isinstance(gpu, dict):
                    continue
                model = (gpu.get("model_name") or "").strip()
                if model and model not in models:
                    models.append(model)
            self.cache.set(cache_key, models)
            return models
        except Exception:
            self.cache.set(cache_key, [])
            return []

    def _load_external_nodes(self) -> List[Dict[str, Any]]:
        if not COLLECTOR_NODES_PATH.exists():
            return []
        with open(COLLECTOR_NODES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("extra_nodes", [])

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
        extra_gpu = extra_data.get("gpu", {})

        physical_gpu_count = int(capacity.get("nvidia.com/gpu", "0"))
        shared_gpu_count = int(capacity.get("nvidia.com/gpu.shared", "0"))
        gpu_count = physical_gpu_count or shared_gpu_count

        gpu_model = labels.get("nvidia.com/gpu.product")
        gpu_models = [gpu_model] if gpu_model else []
        if not gpu_models and gpu_count > 0:
            gpu_models = self._infer_gpu_models_from_aggregator(node_name)
        if not gpu_models and gpu_count > 0:
            gpu_models = extra_gpu.get("models") or []
        if not gpu_models and gpu_count > 0 and labels.get("feature.node.kubernetes.io/pci-10de.present") == "true":
            gpu_models = ["NVIDIA GPU"]
            gpu_model = "NVIDIA GPU"
        elif gpu_models and not gpu_model:
            gpu_model = gpu_models[0]

        gpu_memory_mb = labels.get("nvidia.com/gpu.memory")
        gpu_memory_str = f"{gpu_memory_mb} MiB" if gpu_memory_mb else extra_gpu.get("memory")

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
                family=labels.get("nvidia.com/gpu.family") or extra_gpu.get("family") or ("NVIDIA" if gpu_models else None),
                memory=gpu_memory_str,
                compute_capability=build_compute_capability(labels) or extra_gpu.get("compute_capability"),
                cuda_driver_version=labels.get("nvidia.com/cuda.driver-version.full") or extra_gpu.get("cuda_driver_version"),
                cuda_cores=(
                    self.gpu_map.get_cuda_cores(gpu_model) or extra_gpu.get("cuda_cores")
                    if gpu_model and gpu_model != "NVIDIA GPU"
                    else None
                ),
            ),
            query_enabled=True,
        )

    def build_external_node_inventory(self, raw_node: Dict[str, Any]) -> NodeInventory:
        env = raw_node.get("env", {})
        node_name = raw_node.get("node_name", "")
        node_type = raw_node.get("node_type", "external")
        extra_data = self.extra.get_node_extra(node_name)
        extra_cpu = extra_data.get("cpu", {})
        extra_mem = extra_data.get("memory", {})
        extra_os = extra_data.get("os", {})
        extra_gpu = extra_data.get("gpu", {})

        k8s_ip = (
            env.get("TAILSCALE_IP")
            or env.get("OPENWRT")
            or env.get("LAB_IP")
            or env.get("INSTANCE", "").split(":")[0]
            or ""
        )
        role = env.get("ROLE") or ("ap-gateway" if node_type == "ap_gateway" else node_type)
        gpu_models = extra_gpu.get("models") or []

        return NodeInventory(
            node_name=node_name,
            role=role,
            k8s_ip=k8s_ip,
            os=NodeOSInfo(
                image=extra_os.get("image", "external-node"),
                kernel_version=extra_os.get("kernel_version", ""),
                container_runtime=extra_os.get("container_runtime", "external"),
            ),
            cpu=NodeCPUInfo(
                model_name=extra_cpu.get("model_name"),
                vendor=extra_cpu.get("vendor"),
                family=extra_cpu.get("family"),
                model_id=extra_cpu.get("model_id"),
                cores_total=int(extra_cpu.get("cores_total", 0)),
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
                total_memory=extra_mem.get("total_memory", "N/A"),
                ddr_gen=extra_mem.get("ddr_gen"),
                frequency_mt_s=extra_mem.get("frequency_mt_s"),
                cas_latency=extra_mem.get("cas_latency"),
            ),
            gpu=NodeGPUInfo(
                has_gpu=bool(extra_gpu.get("has_gpu", False)),
                count=int(extra_gpu.get("count", 0)),
                models=gpu_models,
                family=extra_gpu.get("family"),
                memory=extra_gpu.get("memory"),
                compute_capability=extra_gpu.get("compute_capability"),
                cuda_driver_version=extra_gpu.get("cuda_driver_version"),
                cuda_cores=extra_gpu.get("cuda_cores"),
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
        nodes.extend(self.build_external_node_inventory(node) for node in self._load_external_nodes())

        response = NodeListResponse(
            schema="pre6g.node_list.v1",
            ts=int(time.time()),
            count=len(nodes),
            nodes=nodes,
        )
        self.cache.set(cache_key, response)
        return response
