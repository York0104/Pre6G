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
    usage_percent: Optional[float] = None
    used_cores: Optional[float] = None


class NodeStatusMemory(BaseModel):
    usage_percent: Optional[float] = None
    working_set_bytes: Optional[int] = None
    working_set_mib: Optional[int] = None


class NodeStatusDisk(BaseModel):
    root_usage_percent: Optional[float] = None


class NodeStatusGPU(BaseModel):
    status: str
    count: Optional[int] = None
    fb_used_bytes: Optional[int] = None
    fb_used_mib: Optional[float] = None


class NodeStatusAP(BaseModel):
    station_count: Optional[int] = None
    rx_bits_per_s: Optional[float] = None
    tx_bits_per_s: Optional[float] = None
    tx_failed_per_s: Optional[float] = None
    interface_oper_status: Optional[float] = None
    disk_read_bytes_per_s: Optional[float] = None
    disk_write_bytes_per_s: Optional[float] = None
    ssid: Optional[str] = None
    channel: Optional[str] = None
    band: Optional[str] = None
    width_mhz: Optional[str] = None


class NodeStatusRFSoC(BaseModel):
    xrt_device_ready: Optional[bool] = None
    overlay_loaded: Optional[bool] = None
    active_bitfile: Optional[str] = None
    ip_count: Optional[int] = None
    has_rfdc: Optional[bool] = None
    has_dma: Optional[bool] = None
    dma_mm2s_state: Optional[str] = None
    dma_s2mm_state: Optional[str] = None
    dma_channels_status: Optional[str] = None
    has_sysmon: Optional[bool] = None
    temperature_c: Optional[float] = None
    vccint_v: Optional[float] = None
    vccaux_v: Optional[float] = None
    board_power_watts: Optional[float] = None


class NodeStatus(BaseModel):
    node_name: str
    k8s_ip: str
    sources: NodeStatusSources
    cpu: NodeStatusCPU
    memory: NodeStatusMemory
    disk: NodeStatusDisk
    gpu: NodeStatusGPU
    ap: Optional[NodeStatusAP] = None
    rfsoc: Optional[NodeStatusRFSoC] = None


class NodeStatusResponse(BaseModel):
    schema: str
    ts: int
    node: NodeStatus


class NodeStatusListResponse(BaseModel):
    schema: str
    ts: int
    count: int
    nodes: List[NodeStatus]
