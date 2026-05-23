from typing import List, Optional

from pydantic import BaseModel


class NodeOSInfo(BaseModel):
    image: str
    kernel_version: str
    container_runtime: str


class CPUCacheInfo(BaseModel):
    l1d: Optional[str] = None
    l1i: Optional[str] = None
    l2: Optional[str] = None
    l3: Optional[str] = None


class NodeCPUInfo(BaseModel):
    model_name: Optional[str] = None
    vendor: Optional[str] = None
    family: Optional[str] = None
    model_id: Optional[str] = None
    cores_total: int
    base_clock_ghz: Optional[float] = None
    max_clock_ghz: Optional[float] = None
    cache: CPUCacheInfo = CPUCacheInfo()


class NodeMemoryInfo(BaseModel):
    total_memory: str
    ddr_gen: Optional[str] = None
    frequency_mt_s: Optional[int] = None
    cas_latency: Optional[str] = None


class NodeGPUInfo(BaseModel):
    has_gpu: bool
    count: int
    models: List[str] = []
    family: Optional[str] = None
    memory: Optional[str] = None
    compute_capability: Optional[str] = None
    cuda_driver_version: Optional[str] = None
    cuda_cores: Optional[int] = None


class NodeInventory(BaseModel):
    node_name: str
    role: str
    k8s_ip: str
    os: NodeOSInfo
    cpu: NodeCPUInfo
    memory: NodeMemoryInfo
    gpu: NodeGPUInfo
    query_enabled: bool = True


class NodeListResponse(BaseModel):
    schema: str
    ts: int
    count: int
    nodes: List[NodeInventory]


class NodeStatusSources(BaseModel):
    node_metrics: str
    gpu_metrics: str


class NodeStatusCPU(BaseModel):
    usage_percent: float
    used_cores: float


class NodeStatusMemory(BaseModel):
    usage_percent: float
    working_set_bytes: int
    working_set_mib: int


class NodeStatusDisk(BaseModel):
    root_usage_percent: float


class NodeStatusGPU(BaseModel):
    status: str
    count: int
    fb_used_bytes: int
    fb_used_mib: float


class NodeStatus(BaseModel):
    node_name: str
    k8s_ip: str
    sources: NodeStatusSources
    cpu: NodeStatusCPU
    memory: NodeStatusMemory
    disk: NodeStatusDisk
    gpu: NodeStatusGPU


class NodeStatusResponse(BaseModel):
    schema: str
    ts: int
    node: NodeStatus


class NodeStatusListResponse(BaseModel):
    schema: str
    ts: int
    count: int
    nodes: List[NodeStatus]
