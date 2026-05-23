
#!/usr/bin/env python3
# vm_aggregator.py
import os
import json
import time
import urllib.parse
import urllib.request
import re
from typing import Dict, Tuple, Optional, List, Any
import socket
import traceback

VM_URL = os.getenv("VM_URL", "http://100.68.32.118:31888")
OBSERVER = socket.gethostname()

NODE = (os.getenv("NODE") or OBSERVER).strip()
NAMESPACE = os.getenv("NAMESPACE", "intent-lab")

RATE_WINDOW = os.getenv("RATE_WINDOW", "10s")
SMOOTH_WINDOW = os.getenv("SMOOTH_WINDOW", "30s")

MODE = os.getenv("MODE", "fast")  # stable | fast
TRACE = os.getenv("TRACE", "0") == "1"
DEBUG_OUTPUT = os.getenv("DEBUG_OUTPUT", "0") == "1"

QCOUNT = 0

NODE_EXPORTER_INSTANCE = os.getenv("NODE_EXPORTER_INSTANCE", "").strip()
CADVISOR_SELECTOR = os.getenv("CADVISOR_SELECTOR", 'job="kubelet-cadvisor"')

NETDATA_URL = os.getenv("NETDATA_URL", "http://100.68.32.118:32163").rstrip("/")
NETDATA_CHILD_URL = os.getenv("NETDATA_CHILD_URL", NETDATA_URL).rstrip("/")
NETDATA_PARENT_BASE_URL = os.getenv("NETDATA_PARENT_BASE_URL", "http://100.68.32.118:32163").rstrip("/")
NETDATA_HOST = os.getenv("NETDATA_HOST", "").strip()

SYSTEM_PRODUCT_SUFFIX = "-system-product-name"

NETDATA_METRIC_CPU = os.getenv(
    "NETDATA_METRIC_CPU",
    "netdata_prometheus_kubelet_cadvisor_container_cpu_usage_seconds_total_seconds_average",
)
NETDATA_METRIC_MEM = os.getenv(
    "NETDATA_METRIC_MEM",
    "netdata_prometheus_kubelet_cadvisor_container_memory_working_set_bytes_bytes_average",
)

NETDATA_CHART_CPU = os.getenv("NETDATA_CHART_CPU", "system.cpu")
NETDATA_CHART_RAM = os.getenv("NETDATA_CHART_RAM", "system.ram")
NETDATA_CHART_IO = os.getenv("NETDATA_CHART_IO", "system.io")
NETDATA_CHART_LOAD = os.getenv("NETDATA_CHART_LOAD", "system.load")
NETDATA_CHART_CPU_SOME_PRESSURE = os.getenv("NETDATA_CHART_CPU_SOME_PRESSURE", "system.cpu_some_pressure")
NETDATA_CHART_CPU_FULL_PRESSURE = os.getenv("NETDATA_CHART_CPU_FULL_PRESSURE", "system.cpu_full_pressure")
NETDATA_CHART_MEMORY_SOME_PRESSURE = os.getenv("NETDATA_CHART_MEMORY_SOME_PRESSURE", "system.memory_some_pressure")
NETDATA_CHART_MEMORY_FULL_PRESSURE = os.getenv("NETDATA_CHART_MEMORY_FULL_PRESSURE", "system.memory_full_pressure")
NETDATA_CHART_IO_SOME_PRESSURE = os.getenv("NETDATA_CHART_IO_SOME_PRESSURE", "system.io_some_pressure")
NETDATA_CHART_IO_FULL_PRESSURE = os.getenv("NETDATA_CHART_IO_FULL_PRESSURE", "system.io_full_pressure")
NETDATA_CHART_MEM_AVAILABLE = os.getenv("NETDATA_CHART_MEM_AVAILABLE", "mem.available")
NETDATA_CHART_MEM_SWAP = os.getenv("NETDATA_CHART_MEM_SWAP", "mem.swap")
NETDATA_CHART_CPU_TEMP = os.getenv(
    "NETDATA_CHART_CPU_TEMP",
    "sensors.temperature_coretemp-isa-0000_temp1_Package_id_0_input",
)


def clean_name(name: Optional[str]) -> str:
    return (name or "").strip()


def strip_system_product_suffix(name: Optional[str]) -> str:
    s = clean_name(name)
    if s.lower().endswith(SYSTEM_PRODUCT_SUFFIX):
        return s[:-len(SYSTEM_PRODUCT_SUFFIX)]
    return s


def canonical_k8s_node_name(name: Optional[str]) -> str:
    return strip_system_product_suffix(name).lower()


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(float(value))
    except Exception:
        return default


def maybe_round(value: Optional[float], ndigits: int = 6) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), ndigits)
    except Exception:
        return value


def normalize_percent_value(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(value)
    except Exception:
        return value

    if 0.0 <= v <= 1.0:
        return v * 100.0
    return v


def prune_none(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            pruned = prune_none(v)
            if pruned is not None:
                out[k] = pruned
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            pruned = prune_none(item)
            if pruned is not None:
                out.append(pruned)
        return out
    return value


def avg_non_none(values: List[Optional[float]]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def max_non_none(values: List[Optional[float]]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return max(vals)


def min_non_none(values: List[Optional[float]]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return min(vals)


def mib_to_bytes(v_mib: Optional[float]) -> Optional[int]:
    if v_mib is None:
        return None
    try:
        return int(float(v_mib) * 1024 * 1024)
    except Exception:
        return None


def bytes_to_mib(v_bytes: Optional[float]) -> Optional[float]:
    if v_bytes is None:
        return None
    try:
        return float(v_bytes) / (1024.0 * 1024.0)
    except Exception:
        return None


class NetdataClient:
    def __init__(self, base_or_host: str, timeout_s: float = 3.0):
        self.timeout_s = timeout_s

        if base_or_host.startswith("http://") or base_or_host.startswith("https://"):
            self.base_url = base_or_host.rstrip("/")
        else:
            self.base_url = f"http://127.0.0.1:29999/host/{base_or_host}".rstrip("/")

    def _http_get(self, path: str) -> str:
        url = self.base_url + path
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def fetch_allmetrics_prom(self) -> str:
        return self._http_get("/api/v1/allmetrics?format=prometheus")

    def fetch_chart_json(self, chart_id: str, after_s: int = -2) -> dict:
        q = urllib.parse.urlencode({"chart": chart_id, "after": str(after_s), "format": "json"})
        raw = self._http_get("/api/v1/data?" + q)
        return json.loads(raw)

    def charts_index(self) -> dict:
        raw = json.loads(self._http_get("/api/v1/charts"))
        return raw.get("charts", raw)

    def fetch_charts_index(self) -> dict:
        return self.charts_index()

    def resolve_chart_id(self, candidates: List[str]) -> Optional[str]:
        try:
            charts = self.charts_index()
        except Exception:
            return None

        for candidate in candidates:
            if candidate in charts:
                return candidate
        return None

    def resolve_chart_meta(self, candidates: List[str]) -> Optional[dict]:
        try:
            charts = self.charts_index()
        except Exception:
            return None

        for candidate in candidates:
            meta = charts.get(candidate)
            if isinstance(meta, dict):
                out = dict(meta)
                out["_chart_id"] = candidate
                return out
        return None

    def fetch_chart_json_candidates(self, candidates: List[str], after_s: int = -2) -> Optional[dict]:
        chart_id = self.resolve_chart_id(candidates)
        if not chart_id:
            return None
        q = urllib.parse.urlencode({"chart": chart_id, "after": str(after_s), "format": "json"})
        raw = self._http_get("/api/v1/data?" + q)
        return json.loads(raw)

    def resolve_chart_id_fuzzy(self, patterns: List[str]) -> Optional[str]:
        try:
            charts = self.charts_index()
        except Exception:
            return None

        normalized_patterns = [p.strip().lower() for p in patterns if p and p.strip()]
        if not normalized_patterns:
            return None

        for chart_id in charts.keys():
            cid = str(chart_id).lower()
            if all(p in cid for p in normalized_patterns):
                return str(chart_id)
        return None

    def fetch_chart_json_fuzzy(self, patterns: List[str], after_s: int = -2) -> Optional[dict]:
        chart_id = self.resolve_chart_id_fuzzy(patterns)
        if not chart_id:
            return None
        q = urllib.parse.urlencode({"chart": chart_id, "after": str(after_s), "format": "json"})
        raw = self._http_get("/api/v1/data?" + q)
        return json.loads(raw)

    @staticmethod
    def latest_dims(payload: dict) -> Dict[str, float]:
        labels = payload.get("labels") or []
        data = payload.get("data") or []
        if len(labels) < 2 or not data:
            return {}
        last = data[-1]
        out: Dict[str, float] = {}
        for i in range(1, min(len(labels), len(last))):
            try:
                out[str(labels[i])] = float(last[i])
            except Exception:
                continue
        return out

    @staticmethod
    def _unit_scale_to_bytes(value: Optional[float], units: Optional[str]) -> Optional[float]:
        if value is None:
            return None

        u = (units or "").strip().lower().replace("/s", "").replace("per second", "").strip()

        if u in ("b", "byte", "bytes"):
            return float(value)
        if u in ("kib", "kb"):
            return float(value) * 1024.0
        if u in ("mib", "mb"):
            return float(value) * 1024.0 * 1024.0
        if u in ("gib", "gb"):
            return float(value) * 1024.0 * 1024.0 * 1024.0
        if u in ("tib", "tb"):
            return float(value) * 1024.0 * 1024.0 * 1024.0 * 1024.0

        return float(value)

    def latest_scalar_from_chart(
        self,
        chart_id: str,
        prefer_dims: Optional[List[str]] = None,
        sum_all: bool = False,
        absolute: bool = False,
        multiply_scale: bool = False,
    ) -> Optional[float]:
        payload = self.fetch_chart_json(chart_id)
        dims = self.latest_dims(payload)
        if not dims:
            return None

        value: Optional[float] = None
        if prefer_dims:
            for key in prefer_dims:
                if key in dims:
                    value = dims[key]
                    break
        if value is None:
            if sum_all:
                vals = list(dims.values())
                if absolute:
                    vals = [abs(v) for v in vals]
                value = sum(vals)
            else:
                first_key = next(iter(dims.keys()))
                value = dims[first_key]

        if value is None:
            return None

        if multiply_scale:
            value = self._unit_scale_to_bytes(value, payload.get("units"))
        return float(value)

    def chart_dims(self, chart_id: str) -> Dict[str, float]:
        payload = self.fetch_chart_json(chart_id)
        return self.latest_dims(payload)

    @staticmethod
    def _parse_prometheus_text(text: str, metric_name: str) -> List[Tuple[Dict[str, str], float, int]]:
        out: List[Tuple[Dict[str, str], float, int]] = []
        pat = re.compile(
            rf"^{re.escape(metric_name)}(\{{.*\}})?\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s+(\d+)\s*$"
        )
        label_pat = re.compile(r'(\w+)="((?:\\.|[^"\\])*)"')
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            m = pat.match(line)
            if not m:
                continue
            label_blob = m.group(1)
            val = float(m.group(2))
            ts_ms = int(m.group(3))
            labels: Dict[str, str] = {}
            if label_blob:
                inner = label_blob[1:-1]
                for km in label_pat.finditer(inner):
                    k = km.group(1)
                    v = km.group(2)
                    v = bytes(v, "utf-8").decode("unicode_escape")
                    labels[k] = v
            out.append((labels, val, ts_ms))
        return out

    @staticmethod
    def _is_pod_slice_aggregate(labels: Dict[str, str]) -> bool:
        ns = labels.get("namespace")
        pod = labels.get("pod")
        cid = labels.get("id", "")
        if ns in (None, "", "[none]") or pod in (None, "", "[none]"):
            return False
        if not cid.endswith(".slice"):
            return False
        if labels.get("container") != "[none]":
            return False
        if labels.get("image") != "[none]":
            return False
        if labels.get("name") != "[none]":
            return False
        return True

    @staticmethod
    def _is_pod_slice_cpu_aggregate(labels: Dict[str, str]) -> bool:
        if not NetdataClient._is_pod_slice_aggregate(labels):
            return False
        if labels.get("cpu") != "total":
            return False
        return True

    @staticmethod
    def _is_container_scope(labels: Dict[str, str]) -> bool:
        ns = labels.get("namespace")
        pod = labels.get("pod")
        cid = labels.get("id", "")
        img = labels.get("image", "")
        if ns in (None, "", "[none]") or pod in (None, "", "[none]"):
            return False
        if not cid.endswith(".scope"):
            return False
        if "pause:" in img:
            return False
        return True

    def node_cpu_used_percent(self) -> Optional[float]:
        dims = self.chart_dims(NETDATA_CHART_CPU)
        if not dims:
            return None
        idle = dims.get("idle")
        if idle is not None:
            used = 100.0 - float(idle)
        else:
            used = sum(float(v) for v in dims.values())
        return max(0.0, min(100.0, used))

    def node_cpu_breakdown_percent(self) -> Dict[str, Optional[float]]:
        dims = self.chart_dims(NETDATA_CHART_CPU)
        idle = safe_float(dims.get("idle"))
        if idle is None and dims:
            used = sum(float(v) for v in dims.values() if v is not None)
            idle = max(0.0, min(100.0, 100.0 - used))
        return {
            "user": safe_float(dims.get("user")),
            "system": safe_float(dims.get("system")),
            "idle": idle,
            "iowait": safe_float(dims.get("iowait")),
        }

    def node_ram_used_bytes_and_percent(self) -> Tuple[Optional[int], Optional[float]]:
        payload = self.fetch_chart_json(NETDATA_CHART_RAM)
        dims = self.latest_dims(payload)
        if not dims:
            return (None, None)

        free = dims.get("free")
        used = dims.get("used")
        cached = dims.get("cached", dims.get("cache", 0.0))
        buffers = dims.get("buffers", 0.0)

        if free is None or used is None:
            return (None, None)

        total = float(free) + float(used) + float(cached) + float(buffers)
        if total <= 0:
            return (None, None)

        used_bytes = safe_int(self._unit_scale_to_bytes(used, payload.get("units") or "MiB"), None)
        used_pct = (float(used) / total) * 100.0
        return (used_bytes, used_pct)

    def node_ram_breakdown_bytes(self) -> Dict[str, Optional[int]]:
        payload = self.fetch_chart_json(NETDATA_CHART_RAM)
        dims = self.latest_dims(payload)
        if not dims:
            return {
                "mem_total_bytes": None,
                "mem_used_bytes": None,
                "mem_free_bytes": None,
            }

        units = payload.get("units") or "MiB"
        free = safe_float(dims.get("free"))
        used = safe_float(dims.get("used"))
        cached = safe_float(dims.get("cached", dims.get("cache", 0.0)), 0.0)
        buffers = safe_float(dims.get("buffers"), 0.0)

        total = None
        if free is not None and used is not None:
            total = free + used + (cached or 0.0) + (buffers or 0.0)

        return {
            "mem_total_bytes": safe_int(self._unit_scale_to_bytes(total, units), None),
            "mem_used_bytes": safe_int(self._unit_scale_to_bytes(used, units), None),
            "mem_free_bytes": safe_int(self._unit_scale_to_bytes(free, units), None),
        }

    def node_io_read_write_bytes_per_s(self) -> Optional[Dict[str, float]]:
        payload = self.fetch_chart_json(NETDATA_CHART_IO)
        dims = self.latest_dims(payload)
        if not dims:
            return None
        r = dims.get("reads")
        w = dims.get("writes")
        if r is None or w is None:
            return None
        return {
            "read_bytes_per_s": self._unit_scale_to_bytes(r, payload.get("units") or "KiB/s"),
            "write_bytes_per_s": self._unit_scale_to_bytes(abs(float(w)), payload.get("units") or "KiB/s"),
        }

    def node_load(self) -> Dict[str, Optional[float]]:
        dims = self.chart_dims(NETDATA_CHART_LOAD)
        return {
            "load1": safe_float(dims.get("load1")),
            "load5": safe_float(dims.get("load5")),
            "load15": safe_float(dims.get("load15")),
        }

    def psi_chart(self, chart_id: str) -> Dict[str, Optional[float]]:
        dims = self.chart_dims(chart_id)
        return {
            "some": safe_float(dims.get("some", dims.get("avg10", next(iter(dims.values()), None)))),
            "full": safe_float(dims.get("full")),
        }

    def mem_available_bytes(self) -> Optional[float]:
        payload = self.fetch_chart_json(NETDATA_CHART_MEM_AVAILABLE, after_s=-2)
        dims = self.latest_dims(payload)
        val = dims.get("avail")
        if val is None:
            return None

        units = "MiB"
        try:
            meta = self.resolve_chart_meta([NETDATA_CHART_MEM_AVAILABLE])
            if meta and meta.get("units"):
                units = meta["units"]
        except Exception:
            pass

        return self._unit_scale_to_bytes(val, units)

    def cpu_temperature_c(self) -> Optional[float]:
        candidates = [NETDATA_CHART_CPU_TEMP]
        payload = self.fetch_chart_json_candidates(candidates)
        if payload is None:
            payload = self.fetch_chart_json_fuzzy(["temperature", "coretemp"])
        if payload is None:
            payload = self.fetch_chart_json_fuzzy(["package", "temp"])
        if payload is None:
            return None

        dims = self.latest_dims(payload)
        if not dims:
            return None

        preferred_keys = [
            "Package_id_0",
            "package_id_0",
            "input",
            "temp1",
            "temperature",
            "value",
        ]
        for key in preferred_keys:
            if key in dims:
                return safe_float(dims.get(key))

        return safe_float(next(iter(dims.values()), None))

    def pod_mem_bytes(self, prom_text: str, namespace: str, pod: str) -> Optional[int]:
        samples = self._parse_prometheus_text(prom_text, NETDATA_METRIC_MEM)
        for labels, val, _ts in samples:
            if not self._is_pod_slice_aggregate(labels):
                continue
            if labels.get("namespace") != namespace:
                continue
            if labels.get("pod") != pod:
                continue
            return int(val)
        return None

    def namespace_mem_bytes(self, prom_text: str, namespace: str) -> Optional[int]:
        samples = self._parse_prometheus_text(prom_text, NETDATA_METRIC_MEM)
        total = 0.0
        hit = False
        for labels, val, _ts in samples:
            if not self._is_pod_slice_aggregate(labels):
                continue
            if labels.get("namespace") != namespace:
                continue
            hit = True
            total += val
        return int(total) if hit else None

    def pod_cpu_cores(self, prom_text: str, namespace: str, pod: str) -> Optional[float]:
        samples = self._parse_prometheus_text(prom_text, NETDATA_METRIC_CPU)
        for labels, val, _ts in samples:
            if not self._is_pod_slice_cpu_aggregate(labels):
                continue
            if labels.get("namespace") != namespace:
                continue
            if labels.get("pod") != pod:
                continue
            return float(val)

        total = 0.0
        hit = False
        for labels, val, _ts in samples:
            if not self._is_container_scope(labels):
                continue
            if labels.get("namespace") != namespace:
                continue
            if labels.get("pod") != pod:
                continue
            hit = True
            total += val
        return total if hit else None

    def namespace_cpu_cores(self, prom_text: str, namespace: str) -> Optional[float]:
        samples = self._parse_prometheus_text(prom_text, NETDATA_METRIC_CPU)
        total = 0.0
        hit = False
        for labels, val, _ts in samples:
            if not self._is_pod_slice_cpu_aggregate(labels):
                continue
            if labels.get("namespace") != namespace:
                continue
            hit = True
            total += val
        if hit:
            return total

        total = 0.0
        hit = False
        for labels, val, _ts in samples:
            if not self._is_container_scope(labels):
                continue
            if labels.get("namespace") != namespace:
                continue
            hit = True
            total += val
        return total if hit else None


def count_local_namespace_pods(state: dict) -> int:
    meta = state.get("meta", {})
    target_node = canonical_k8s_node_name(meta.get("target_node") or meta.get("target_host"))
    cluster = state.get("cluster_semantic", {})

    count = 0
    for dep in cluster.get("deployments", []):
        for pod in dep.get("pods", []):
            if canonical_k8s_node_name(pod.get("node")) == target_node:
                count += 1

    for pod in cluster.get("standalone_pods", []):
        if canonical_k8s_node_name(pod.get("node")) == target_node:
            count += 1

    return count


def list_netdata_mirrored_hosts() -> List[str]:
    url = f"{NETDATA_PARENT_BASE_URL}/api/v1/info"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    hosts = payload.get("mirrored_hosts") or []
    return [h for h in hosts if isinstance(h, str) and h.strip()]


def resolve_netdata_host_for_node(node_name: str) -> str:
    explicit = clean_name(NETDATA_HOST)
    if explicit:
        return explicit

    hosts = list_netdata_mirrored_hosts()
    if not hosts:
        return node_name

    target_key = canonical_k8s_node_name(node_name)

    for h in hosts:
        if canonical_k8s_node_name(h) == target_key:
            return h

    prefix_matches = [h for h in hosts if canonical_k8s_node_name(h).startswith(target_key)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]

    reverse_prefix_matches = [h for h in hosts if target_key.startswith(canonical_k8s_node_name(h))]
    if len(reverse_prefix_matches) == 1:
        return reverse_prefix_matches[0]

    contains_matches = [h for h in hosts if target_key in canonical_k8s_node_name(h)]
    if len(contains_matches) == 1:
        return contains_matches[0]

    return node_name


def build_netdata_host_scoped_client(target_node: str) -> Tuple[NetdataClient, str]:
    try:
        resolved_host = resolve_netdata_host_for_node(target_node)
    except Exception:
        resolved_host = target_node
    base_url = f"{NETDATA_PARENT_BASE_URL}/host/{resolved_host}"
    return NetdataClient(base_url), resolved_host


netdata_child_local = NetdataClient(NETDATA_CHILD_URL)


def vm_query(promql: str):
    global QCOUNT
    QCOUNT += 1
    if TRACE:
        print(f"[vm_query #{QCOUNT}] {promql}")

    url = f"{VM_URL}/api/v1/query?" + urllib.parse.urlencode({"query": promql})
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=7) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if data.get("status") != "success":
        raise RuntimeError(f"vm_query non-success: {data}\nPROMQL={promql}\nURL={url}")
    return data["data"].get("result", [])


def vm_query_optional(promql: str):
    try:
        return vm_query(promql)
    except Exception:
        return []


def split_instance_host(instance: str) -> str:
    s = clean_name(instance)
    if not s:
        return ""
    if ":" in s:
        return s.rsplit(":", 1)[0]
    return s


def resolve_node_internal_ip_from_k8s(node_name: str) -> Optional[str]:
    node_name = clean_name(node_name)
    if not node_name:
        return None

    queries = [
        f'kube_node_status_addresses{{node="{node_name}",type="InternalIP"}}',
        f'kube_node_status_addresses{{node="{canonical_k8s_node_name(node_name)}",type="InternalIP"}}',
    ]

    for q in queries:
        result = vm_query_optional(q)
        for item in result:
            metric = item.get("metric", {})
            for key in ("address", "internal_ip", "ip"):
                if metric.get(key):
                    return clean_name(metric.get(key))
    return None


def resolve_host_ip_by_dns(name: str) -> Optional[str]:
    name = clean_name(name)
    if not name:
        return None
    try:
        return socket.gethostbyname(name)
    except Exception:
        return None


def first_value(result, default: Optional[float] = 0.0) -> Optional[float]:
    if not result:
        return default
    try:
        return float(result[0]["value"][1])
    except Exception:
        return default


def first_value_optional(result) -> Optional[float]:
    if not result:
        return None
    try:
        return float(result[0]["value"][1])
    except Exception:
        return None


def vector_to_map(result, key_label: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for item in result:
        m = item.get("metric", {})
        if key_label in m:
            try:
                out[m[key_label]] = float(item["value"][1])
            except Exception:
                continue
    return out


def sum_values(result) -> float:
    total = 0.0
    for item in result:
        try:
            total += float(item["value"][1])
        except Exception:
            continue
    return total


def rate_query(metric: str, instance: str, extra_filters: str = "", default: Optional[float] = None) -> Optional[float]:
    filters = [f'instance="{instance}"']
    if extra_filters:
        filters.append(extra_filters)
    label_expr = ",".join(filters)
    q = f'sum(rate({metric}{{{label_expr}}}[{RATE_WINDOW}]))'
    return first_value_optional(vm_query_optional(q)) if default is None else first_value(vm_query_optional(q), default)


def scalar_optional(promql: str) -> Optional[float]:
    return first_value_optional(vm_query_optional(promql))


def sum_rate_optional(metric: str, instance: str, rate_window: Optional[str] = None) -> Optional[float]:
    rw = rate_window or RATE_WINDOW
    q = f'sum(rate({metric}{{instance="{instance}"}}[{rw}]))'
    return first_value_optional(vm_query_optional(q))


def scalar_sum_optional(metric: str, instance: str) -> Optional[float]:
    q = f'sum({metric}{{instance="{instance}"}})'
    return first_value_optional(vm_query_optional(q))


def build_identity_debug(
    observer: str,
    target_host: str,
    target_k8s_node: str,
    node_exporter_instance: str,
    resolved_netdata_host: str,
) -> dict:
    return {
        "observer": observer,
        "target_host": target_host,
        "target_k8s_node": target_k8s_node,
        "node_exporter_instance": node_exporter_instance,
        "resolved_netdata_host": resolved_netdata_host,
    }


def build_gpu_workload_map(gpu_workloads: List[dict], namespace: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for item in gpu_workloads:
        if item.get("namespace") != namespace:
            continue
        pod = item.get("pod")
        if not pod:
            continue
        out[pod] = {
            "uses_gpu": True,
            "fb_used_bytes": item.get("fb_used_bytes"),
        }
    return out


def default_gpu_info() -> dict:
    return {
        "uses_gpu": False,
        "fb_used_bytes": None,
    }


def gpu_workload_pod_names(gpu_workloads: List[dict], namespace: str) -> List[str]:
    names = []
    for item in gpu_workloads:
        if item.get("namespace") != namespace:
            continue
        pod = item.get("pod")
        if pod:
            names.append(pod)
    return sorted(set(names))


def pick_node_exporter_instance(
    target_host: str,
    target_k8s_node: Optional[str] = None,
) -> Tuple[str, str]:
    if NODE_EXPORTER_INSTANCE:
        return NODE_EXPORTER_INSTANCE, "env_override"

    vec = vm_query('node_uname_info{job="node-exporter"}')
    if not vec:
        raise RuntimeError("No node_uname_info found for job=node-exporter")

    exporters = []
    for item in vec:
        m = item.get("metric", {})
        inst = clean_name(m.get("instance"))
        nn = clean_name(m.get("nodename"))
        if not inst:
            continue
        exporters.append({
            "instance": inst,
            "instance_host": split_instance_host(inst),
            "nodename": nn,
            "canonical_nodename": canonical_k8s_node_name(nn),
        })

    target_keys = set()
    if target_host:
        target_keys.add(canonical_k8s_node_name(target_host))
    if target_k8s_node:
        target_keys.add(canonical_k8s_node_name(target_k8s_node))

    for ex in exporters:
        if ex["canonical_nodename"] in target_keys:
            return ex["instance"], "nodename_exact"

    for ex in exporters:
        ex_key = ex["canonical_nodename"]
        for tk in target_keys:
            if ex_key.startswith(tk) or tk.startswith(ex_key):
                return ex["instance"], "nodename_prefix"

    candidate_ips = []
    for cand in [target_k8s_node, target_host]:
        ip = resolve_node_internal_ip_from_k8s(cand or "")
        if ip and ip not in candidate_ips:
            candidate_ips.append(ip)

    for cand in [target_host, target_k8s_node]:
        ip = resolve_host_ip_by_dns(cand or "")
        if ip and ip not in candidate_ips:
            candidate_ips.append(ip)

    for ip in candidate_ips:
        for ex in exporters:
            if ex["instance_host"] == ip:
                return ex["instance"], f"instance_ip:{ip}"

    if len(exporters) == 1:
        return exporters[0]["instance"], "single_exporter_fallback"

    raise RuntimeError(
        f"Cannot find node-exporter instance for "
        f"target_host={target_host}, target_k8s_node={target_k8s_node}. "
        f"Available exporters="
        f"{[{'nodename': e['nodename'], 'instance': e['instance']} for e in exporters]}"
    )


def get_node_cpu_cores_total(instance: str) -> Optional[int]:
    q = f'count(count by (cpu) (node_cpu_seconds_total{{instance="{instance}"}}))'
    return safe_int(first_value_optional(vm_query_optional(q)), None)


def get_node_memory_total_bytes(instance: str) -> Optional[int]:
    q = f'node_memory_MemTotal_bytes{{instance="{instance}"}}'
    return safe_int(first_value_optional(vm_query_optional(q)), None)


def collect_node_perf_metrics(instance: str) -> dict:
    out = {}

    out["cpu_cycles"] = sum_rate_optional("node_perf_cpu_cycles_total", instance)
    out["instructions"] = sum_rate_optional("node_perf_instructions_total", instance)

    stalled_frontend = sum_rate_optional("node_perf_stalled_cycles_frontend_total", instance)
    stalled_backend = sum_rate_optional("node_perf_stalled_cycles_backend_total", instance)

    if stalled_frontend is None and stalled_backend is None:
        out["stalled_cycles"] = None
    else:
        out["stalled_cycles"] = (stalled_frontend or 0.0) + (stalled_backend or 0.0)

    if out["cpu_cycles"] and out["instructions"] and out["cpu_cycles"] > 0:
        out["instructions_per_cycle"] = out["instructions"] / out["cpu_cycles"]
    else:
        out["instructions_per_cycle"] = None

    out["branch_instructions"] = sum_rate_optional("node_perf_branch_instructions_total", instance)
    out["branch_misses"] = sum_rate_optional("node_perf_branch_misses_total", instance)

    out["cache_bpu_read_hits"] = sum_rate_optional("node_perf_cache_bpu_read_hits_total", instance)
    out["cache_bpu_read_misses"] = sum_rate_optional("node_perf_cache_bpu_read_misses_total", instance)
    out["cache_l1d_read_hits"] = sum_rate_optional("node_perf_cache_l1d_read_hits_total", instance)
    out["cache_l1d_read_misses"] = sum_rate_optional("node_perf_cache_l1d_read_misses_total", instance)
    out["cache_l1d_write_hits"] = sum_rate_optional("node_perf_cache_l1d_write_hits_total", instance)

    out["perf_event_paranoid"] = scalar_optional(
        f'node_sysctl_kernel_perf_event_paranoid{{instance="{instance}"}}'
    )

    return out


def collect_node_extended_metrics(instance: str) -> dict:
    metrics = {}

    metrics["cpu_usage_percent"] = scalar_optional(
        f'100 - (avg(rate(node_cpu_seconds_total{{instance="{instance}",mode="idle"}}[{RATE_WINDOW}])) * 100)'
    )
    metrics["memory_usage_percent"] = scalar_optional(
        f'100 * (1 - (node_memory_MemAvailable_bytes{{instance="{instance}"}} / '
        f'node_memory_MemTotal_bytes{{instance="{instance}"}}))'
    )
    metrics["disk_root_usage_percent"] = scalar_optional(
        f'max(100 * (1 - (node_filesystem_avail_bytes{{instance="{instance}",mountpoint="/",fstype!~"tmpfs|overlay"}} '
        f'/ node_filesystem_size_bytes{{instance="{instance}",mountpoint="/",fstype!~"tmpfs|overlay"}})))'
    )

    metrics["load1"] = scalar_optional(f'node_load1{{instance="{instance}"}}')
    metrics["load5"] = scalar_optional(f'node_load5{{instance="{instance}"}}')
    metrics["load15"] = scalar_optional(f'node_load15{{instance="{instance}"}}')

    metrics["cpu_pressure_waiting_seconds_per_s"] = scalar_optional(
        f'sum(rate(node_pressure_cpu_waiting_seconds_total{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )
    metrics["memory_pressure_waiting_seconds_per_s"] = scalar_optional(
        f'sum(rate(node_pressure_memory_waiting_seconds_total{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )
    metrics["memory_pressure_stalled_seconds_per_s"] = scalar_optional(
        f'sum(rate(node_pressure_memory_stalled_seconds_total{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )
    metrics["io_pressure_waiting_seconds_per_s"] = scalar_optional(
        f'sum(rate(node_pressure_io_waiting_seconds_total{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )
    metrics["io_pressure_stalled_seconds_per_s"] = scalar_optional(
        f'sum(rate(node_pressure_io_stalled_seconds_total{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )

    metrics["schedstat_running_seconds_per_s"] = scalar_optional(
        f'sum(rate(node_schedstat_running_seconds_total{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )
    metrics["schedstat_waiting_seconds_per_s"] = scalar_optional(
        f'sum(rate(node_schedstat_waiting_seconds_total{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )
    metrics["schedstat_timeslices_per_s"] = scalar_optional(
        f'sum(rate(node_schedstat_timeslices_total{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )

    metrics["pgmajfault_per_s"] = scalar_optional(
        f'sum(rate(node_vmstat_pgmajfault{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )
    metrics["pswpin_pages_per_s"] = scalar_optional(
        f'sum(rate(node_vmstat_pswpin{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )
    metrics["pswpout_pages_per_s"] = scalar_optional(
        f'sum(rate(node_vmstat_pswpout{{instance="{instance}"}}[{RATE_WINDOW}]))'
    )

    metrics["disk_read_bytes_per_s"] = scalar_optional(
        f'sum(rate(node_disk_read_bytes_total{{instance="{instance}",device!~"loop.*|ram.*"}}[{RATE_WINDOW}]))'
    )
    metrics["disk_write_bytes_per_s"] = scalar_optional(
        f'sum(rate(node_disk_written_bytes_total{{instance="{instance}",device!~"loop.*|ram.*"}}[{RATE_WINDOW}]))'
    )
    metrics["network_receive_bytes_per_s"] = scalar_optional(
        f'sum(rate(node_network_receive_bytes_total{{instance="{instance}",device!="lo"}}[{RATE_WINDOW}]))'
    )
    metrics["network_transmit_bytes_per_s"] = scalar_optional(
        f'sum(rate(node_network_transmit_bytes_total{{instance="{instance}",device!="lo"}}[{RATE_WINDOW}]))'
    )

    metrics["mem_available_bytes"] = scalar_optional(
        f'node_memory_MemAvailable_bytes{{instance="{instance}"}}'
    )
    metrics["mem_total_bytes"] = scalar_optional(
        f'node_memory_MemTotal_bytes{{instance="{instance}"}}'
    )

    swap_total = scalar_optional(f'node_memory_SwapTotal_bytes{{instance="{instance}"}}')
    swap_free = scalar_optional(f'node_memory_SwapFree_bytes{{instance="{instance}"}}')
    if swap_total is not None and swap_free is not None:
        swap_used = max(0.0, swap_total - swap_free)
    else:
        swap_used = None

    perf_metrics = collect_node_perf_metrics(instance)
    metrics.update({
        "swap_used_bytes": swap_used,
        "swap_total_bytes": swap_total,
        "swap_free_bytes": swap_free,
        "perf_cpu_cycles": perf_metrics.get("cpu_cycles"),
        "perf_instructions": perf_metrics.get("instructions"),
        "perf_instructions_per_cycle": perf_metrics.get("instructions_per_cycle"),
        "perf_stalled_cycles": perf_metrics.get("stalled_cycles"),
        "perf_branch_instructions": perf_metrics.get("branch_instructions"),
        "perf_branch_misses": perf_metrics.get("branch_misses"),
        "perf_cache_bpu_read_hits": perf_metrics.get("cache_bpu_read_hits"),
        "perf_cache_bpu_read_misses": perf_metrics.get("cache_bpu_read_misses"),
        "perf_cache_l1d_read_hits": perf_metrics.get("cache_l1d_read_hits"),
        "perf_cache_l1d_read_misses": perf_metrics.get("cache_l1d_read_misses"),
        "perf_cache_l1d_write_hits": perf_metrics.get("cache_l1d_write_hits"),
        "perf_event_paranoid": perf_metrics.get("perf_event_paranoid"),
    })

    return metrics


def collect_netdata_extended_metrics(client: NetdataClient, debug: dict) -> dict:
    out: dict = {}
    try:
        cpu_used_pct = client.node_cpu_used_percent()
    except Exception as e:
        cpu_used_pct = None
        debug["netdata_node_cpu_error"] = str(e)

    try:
        cpu_breakdown = client.node_cpu_breakdown_percent()
    except Exception as e:
        cpu_breakdown = {
            "user": None,
            "system": None,
            "idle": None,
            "iowait": None,
        }
        debug["netdata_node_cpu_breakdown_error"] = str(e)

    try:
        ram_used_bytes, ram_used_pct = client.node_ram_used_bytes_and_percent()
    except Exception as e:
        ram_used_bytes, ram_used_pct = (None, None)
        debug["netdata_node_ram_error"] = str(e)

    try:
        ram_breakdown = client.node_ram_breakdown_bytes()
    except Exception as e:
        ram_breakdown = {
            "mem_total_bytes": None,
            "mem_used_bytes": None,
            "mem_free_bytes": None,
        }
        debug["netdata_node_ram_breakdown_error"] = str(e)

    try:
        io_rw = client.node_io_read_write_bytes_per_s()
    except Exception as e:
        io_rw = None
        debug["netdata_node_io_error"] = str(e)

    try:
        load = client.node_load()
    except Exception as e:
        load = {"load1": None, "load5": None, "load15": None}
        debug["netdata_load_error"] = str(e)

    for key, chart in [
        ("cpu_some_pressure_percent", NETDATA_CHART_CPU_SOME_PRESSURE),
        ("memory_some_pressure_percent", NETDATA_CHART_MEMORY_SOME_PRESSURE),
        ("memory_full_pressure_percent", NETDATA_CHART_MEMORY_FULL_PRESSURE),
        ("io_some_pressure_percent", NETDATA_CHART_IO_SOME_PRESSURE),
        ("io_full_pressure_percent", NETDATA_CHART_IO_FULL_PRESSURE),
    ]:
        try:
            out[key] = client.latest_scalar_from_chart(chart, sum_all=False)
        except Exception as e:
            out[key] = None
            debug[f"netdata_{key}_error"] = str(e)

    try:
        cpu_full_candidates = [
            os.getenv("NETDATA_CHART_CPU_FULL_PRESSURE", "").strip(),
            NETDATA_CHART_CPU_FULL_PRESSURE,
            "system.cpu_full_pressure",
            "cpu.cpu_full_pressure",
            "system.cpu.full_pressure",
        ]
        cpu_full_candidates = [x for x in cpu_full_candidates if x]
        payload = client.fetch_chart_json_candidates(cpu_full_candidates)
        if payload is not None:
            dims = client.latest_dims(payload)
            out["cpu_full_pressure_percent"] = safe_float(dims.get("full"))
        else:
            out["cpu_full_pressure_percent"] = None
    except Exception as e:
        out["cpu_full_pressure_percent"] = None
        debug["netdata_cpu_full_pressure_percent_error"] = str(e)

    try:
        mem_available_bytes = client.mem_available_bytes()
    except Exception as e:
        mem_available_bytes = None
        debug["netdata_mem_available_error"] = str(e)

    try:
        cpu_temperature_c = client.cpu_temperature_c()
    except Exception as e:
        cpu_temperature_c = None
        debug["netdata_cpu_temperature_error"] = str(e)

    out.update({
        "cpu_usage_percent": cpu_used_pct,
        "cpu_user_percent": cpu_breakdown.get("user"),
        "cpu_system_percent": cpu_breakdown.get("system"),
        "cpu_idle_percent": cpu_breakdown.get("idle"),
        "cpu_iowait_percent": cpu_breakdown.get("iowait"),
        "memory_usage_percent": ram_used_pct,
        "node_memory_working_set_bytes": ram_used_bytes,
        "mem_total_bytes": ram_breakdown.get("mem_total_bytes"),
        "mem_used_bytes": ram_breakdown.get("mem_used_bytes"),
        "mem_free_bytes": ram_breakdown.get("mem_free_bytes"),
        "disk_read_bytes_per_s": io_rw.get("read_bytes_per_s") if io_rw else None,
        "disk_write_bytes_per_s": io_rw.get("write_bytes_per_s") if io_rw else None,
        "load1": load.get("load1"),
        "load5": load.get("load5"),
        "load15": load.get("load15"),
        "mem_available_bytes": mem_available_bytes,
        "cpu_temperature_c": cpu_temperature_c,
    })
    return out


def apply_netdata_overlay(state: dict, netdata_host_scoped: NetdataClient, resolved_netdata_host: str) -> dict:
    ns = state.get("meta", {}).get("namespace", NAMESPACE)
    state.setdefault("_debug", {})
    debug = state["_debug"]
    debug["netdata_child_base_url"] = netdata_child_local.base_url
    debug["netdata_parent_base_url"] = netdata_host_scoped.base_url

    netdata_metrics = collect_netdata_extended_metrics(netdata_host_scoped, debug)

    cores_total = state.get("_debug", {}).get("node_cpu_cores_total")
    cpu_used_pct = netdata_metrics.get("cpu_usage_percent")
    cpu_used_cores = (
        (cpu_used_pct / 100.0) * float(cores_total)
        if (cpu_used_pct is not None and cores_total is not None)
        else None
    )

    state.setdefault("target_node_semantic", {})
    state["target_node_semantic"]["node_pressure_instant"] = {
        "source": "netdata",
        "update_every_s": 1,
        "window_s": 1,
        "node_cpu_cores": cpu_used_cores,
        "node_memory_working_set_bytes": netdata_metrics.get("node_memory_working_set_bytes"),
        "cpu_usage_percent": cpu_used_pct,
        "cpu_user_percent": netdata_metrics.get("cpu_user_percent"),
        "cpu_system_percent": netdata_metrics.get("cpu_system_percent"),
        "cpu_idle_percent": netdata_metrics.get("cpu_idle_percent"),
        "cpu_iowait_percent": netdata_metrics.get("cpu_iowait_percent"),
        "memory_usage_percent": netdata_metrics.get("memory_usage_percent"),
        "mem_total_bytes": netdata_metrics.get("mem_total_bytes"),
        "mem_used_bytes": netdata_metrics.get("mem_used_bytes"),
        "mem_free_bytes": netdata_metrics.get("mem_free_bytes"),
        "cpu_temperature_c": netdata_metrics.get("cpu_temperature_c"),
        "disk_root_usage_percent": state.get("target_node_semantic", {}).get("node_pressure", {}).get("disk_root_usage_percent"),
        "node_disk_io": {
            "read_bytes_per_s": netdata_metrics.get("disk_read_bytes_per_s"),
            "write_bytes_per_s": netdata_metrics.get("disk_write_bytes_per_s"),
        },
        "load_average": {
            "load1": netdata_metrics.get("load1"),
            "load5": netdata_metrics.get("load5"),
            "load15": netdata_metrics.get("load15"),
        },
        "pressure": {
            "cpu_some_pressure_percent": netdata_metrics.get("cpu_some_pressure_percent"),
            "cpu_full_pressure_percent": netdata_metrics.get("cpu_full_pressure_percent"),
            "memory_some_pressure_percent": netdata_metrics.get("memory_some_pressure_percent"),
            "memory_full_pressure_percent": netdata_metrics.get("memory_full_pressure_percent"),
            "io_some_pressure_percent": netdata_metrics.get("io_some_pressure_percent"),
            "io_full_pressure_percent": netdata_metrics.get("io_full_pressure_percent"),
        },
        "memory_capacity": {
            "source": "netdata+node_exporter",
            "mem_available_bytes": netdata_metrics.get("mem_available_bytes"),
            "swap_used_bytes": state["target_node_semantic"]["node_compute_features"]["ram_capacity"].get("swap_used_bytes"),
            "swap_total_bytes": state["target_node_semantic"]["node_compute_features"]["ram_capacity"].get("swap_total_bytes"),
            "swap_free_bytes": state["target_node_semantic"]["node_compute_features"]["ram_capacity"].get("swap_free_bytes"),
        },
        "perf": {
            "source": "node_exporter_perf",
            "cpu_cycles": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_cpu_cycles"),
            "instructions": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_instructions"),
            "instructions_per_cycle": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_instructions_per_cycle"),
            "stalled_cycles": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_stalled_cycles"),
            "branch_instructions": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_branch_instructions"),
            "branch_misses": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_branch_misses"),
            "cache_bpu_read_hits": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_cache_bpu_read_hits"),
            "cache_bpu_read_misses": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_cache_bpu_read_misses"),
            "cache_l1d_read_hits": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_cache_l1d_read_hits"),
            "cache_l1d_read_misses": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_cache_l1d_read_misses"),
            "cache_l1d_write_hits": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_cache_l1d_write_hits"),
            "perf_event_paranoid": state["target_node_semantic"]["node_compute_features"]["cpu_compute"].get("perf_event_paranoid"),
        },
    }

    debug["netdata_node_cpu_used_percent"] = cpu_used_pct
    debug["netdata_node_mem_used_percent"] = netdata_metrics.get("memory_usage_percent")
    debug["netdata_node_cpu_cores_total"] = cores_total
    debug["netdata_node_cpu_cores"] = cpu_used_cores
    debug["netdata_node_mem_used_bytes"] = netdata_metrics.get("node_memory_working_set_bytes")
    debug["netdata_node_cpu_breakdown"] = {
        "user": netdata_metrics.get("cpu_user_percent"),
        "system": netdata_metrics.get("cpu_system_percent"),
        "idle": netdata_metrics.get("cpu_idle_percent"),
        "iowait": netdata_metrics.get("cpu_iowait_percent"),
    }
    debug["netdata_node_mem_breakdown"] = {
        "mem_total_bytes": netdata_metrics.get("mem_total_bytes"),
        "mem_used_bytes": netdata_metrics.get("mem_used_bytes"),
        "mem_free_bytes": netdata_metrics.get("mem_free_bytes"),
        "mem_available_bytes": netdata_metrics.get("mem_available_bytes"),
    }
    debug["netdata_cpu_temperature_c"] = netdata_metrics.get("cpu_temperature_c")
    debug["netdata_node_io"] = {
        "read_bytes_per_s": netdata_metrics.get("disk_read_bytes_per_s"),
        "write_bytes_per_s": netdata_metrics.get("disk_write_bytes_per_s"),
    }

    cpu_compute = state["target_node_semantic"]["node_compute_features"]["cpu_compute"]
    cpu_compute["cpu_user_percent"] = netdata_metrics.get("cpu_user_percent")
    cpu_compute["cpu_system_percent"] = netdata_metrics.get("cpu_system_percent")
    cpu_compute["cpu_idle_percent"] = netdata_metrics.get("cpu_idle_percent")
    cpu_compute["cpu_iowait_percent"] = netdata_metrics.get("cpu_iowait_percent")
    cpu_compute["cpu_temperature_c"] = netdata_metrics.get("cpu_temperature_c")

    ram_capacity = state["target_node_semantic"]["node_compute_features"]["ram_capacity"]
    if netdata_metrics.get("mem_total_bytes") is not None:
        ram_capacity["mem_total_bytes"] = netdata_metrics.get("mem_total_bytes")
    ram_capacity["mem_used_bytes"] = netdata_metrics.get("mem_used_bytes")
    ram_capacity["mem_free_bytes"] = netdata_metrics.get("mem_free_bytes")
    if netdata_metrics.get("mem_available_bytes") is not None:
        ram_capacity["mem_available_bytes"] = netdata_metrics.get("mem_available_bytes")

    try:
        prom = netdata_host_scoped.fetch_allmetrics_prom()
    except Exception as e:
        debug["netdata_allmetrics_error"] = str(e)
        return state

    ns_mem = netdata_host_scoped.namespace_mem_bytes(prom, ns)
    ns_cpu = netdata_host_scoped.namespace_cpu_cores(prom, ns)
    local_ns_pod_count = count_local_namespace_pods(state)
    has_local_namespace_workload = local_ns_pod_count > 0
    namespace_status = "ok" if (ns_mem is not None or ns_cpu is not None) else "no_local_workload_or_not_observed"

    if not has_local_namespace_workload:
        namespace_status = "no_local_workload_on_target_node"
        if ns_mem is None:
            ns_mem = 0
        if ns_cpu is None:
            ns_cpu = 0.0

    state["target_node_semantic"]["namespace_total_instant_local"] = {
        "source": "netdata_parent_host_scoped",
        "scope": "host",
        "host": resolved_netdata_host,
        "status": namespace_status,
        "cpu_cores_rate": ns_cpu,
        "memory_working_set_bytes": int(ns_mem) if ns_mem is not None else None,
    }

    debug["netdata_ns"] = ns
    debug["netdata_ns_cpu_local"] = ns_cpu
    debug["netdata_ns_mem_local"] = ns_mem
    debug["netdata_parent_host"] = resolved_netdata_host
    debug["netdata_parent_has_namespace"] = (f'namespace="{ns}"' in prom)
    debug["netdata_parent_has_cpu_metric"] = (NETDATA_METRIC_CPU in prom)
    debug["netdata_parent_has_mem_metric"] = (NETDATA_METRIC_MEM in prom)
    debug["netdata_dep_pod_overlay_enabled"] = False
    debug["netdata_local_namespace_pod_count"] = local_ns_pod_count

    if not debug["netdata_parent_has_namespace"]:
        if not has_local_namespace_workload:
            debug["netdata_overlay_skipped_reason"] = "no_local_namespace_pods_on_target_node"
        else:
            debug["netdata_overlay_skipped_reason"] = "namespace_metrics_not_found_on_target_host"
        return state
    if not (debug["netdata_parent_has_cpu_metric"] or debug["netdata_parent_has_mem_metric"]):
        debug["netdata_overlay_skipped_reason"] = "cadvisor_metrics_not_found_in_allmetrics"
        return state

    return state


def collect_state_for_node(
    node_name: str,
    namespace: Optional[str] = None,
    k8s_node_name: Optional[str] = None,
):
    global QCOUNT
    if not VM_URL:
        raise RuntimeError("VM_URL is required")

    target_host = clean_name(node_name or OBSERVER)
    target_k8s_node = canonical_k8s_node_name(k8s_node_name or target_host)
    target_namespace = clean_name(namespace or NAMESPACE)

    QCOUNT = 0
    ts = int(time.time())

    netdata_host_scoped = None
    resolved_netdata_host = target_host
    netdata_init_error = None
    try:
        netdata_host_scoped, resolved_netdata_host = build_netdata_host_scoped_client(target_host)
    except Exception as e:
        netdata_init_error = str(e)

    node_exporter_instance, node_exporter_match_method = pick_node_exporter_instance(
        target_host=target_host,
        target_k8s_node=target_k8s_node,
    )
    node_cpu_cores_total = get_node_cpu_cores_total(node_exporter_instance)
    node_memory_total_bytes = get_node_memory_total_bytes(node_exporter_instance)

    ns_cpu = first_value(vm_query(
        f'sum(rate(container_cpu_usage_seconds_total{{{CADVISOR_SELECTOR},namespace="{target_namespace}",container!=""}}[{RATE_WINDOW}]))'
    ), 0.0)
    ns_mem = first_value(vm_query(
        f'sum(container_memory_working_set_bytes{{{CADVISOR_SELECTOR},namespace="{target_namespace}",container!=""}})'
    ), 0.0)
    ns_running = safe_int(first_value(vm_query(
        f'sum(kube_pod_status_phase{{namespace="{target_namespace}",phase="Running"}} == 1)'
    ), 0.0), 0)
    ns_ready = safe_int(first_value(vm_query(
        f'sum(max by(pod) (kube_pod_status_ready{{namespace="{target_namespace}",condition="true"}} == 1))'
    ), 0.0), 0)

    node_metrics = collect_node_extended_metrics(node_exporter_instance)

    dcgm_fields = {
        "_utilization_percent": 'DCGM_FI_DEV_GPU_UTIL',
        "_fb_total_mib": 'DCGM_FI_DEV_FB_TOTAL',
        "_fb_used_mib": 'DCGM_FI_DEV_FB_USED',
        "_fb_free_mib": 'DCGM_FI_DEV_FB_FREE',
        "_fb_reserved_mib": 'DCGM_FI_DEV_FB_RESERVED',
        "_fb_used_percent": 'DCGM_FI_DEV_FB_USED_PERCENT',
        "_temperature_c": 'DCGM_FI_DEV_GPU_TEMP',
        "_memory_temperature_c": 'DCGM_FI_DEV_MEMORY_TEMP',
        "_power_watts": 'DCGM_FI_DEV_POWER_USAGE',
        "_energy_mj": 'DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION',
        "_mem_copy_util_percent": 'DCGM_FI_DEV_MEM_COPY_UTIL',
        "_sm_clock_mhz": 'DCGM_FI_DEV_SM_CLOCK',
        "_mem_clock_mhz": 'DCGM_FI_DEV_MEM_CLOCK',
        "_pstate": 'DCGM_FI_DEV_PSTATE',
        "_power_violation_ns": 'DCGM_FI_DEV_POWER_VIOLATION',
        "_thermal_violation_ns": 'DCGM_FI_DEV_THERMAL_VIOLATION',
        "_pcie_tx_throughput": 'DCGM_FI_DEV_PCIE_TX_THROUGHPUT',
        "_pcie_rx_throughput": 'DCGM_FI_DEV_PCIE_RX_THROUGHPUT',
        "_pcie_replay_counter": 'DCGM_FI_DEV_PCIE_REPLAY_COUNTER',
        "_pcie_link_gen": 'DCGM_FI_DEV_PCIE_LINK_GEN',
        "_pcie_link_width": 'DCGM_FI_DEV_PCIE_LINK_WIDTH',
    }

    GPU_FIELD_DEBUG_MAP = {
        "_utilization_percent": "DCGM_FI_DEV_GPU_UTIL",
        "_fb_total_mib": "DCGM_FI_DEV_FB_TOTAL",
        "_fb_used_mib": "DCGM_FI_DEV_FB_USED",
        "_fb_free_mib": "DCGM_FI_DEV_FB_FREE",
        "_fb_reserved_mib": "DCGM_FI_DEV_FB_RESERVED",
        "_fb_used_percent": "DCGM_FI_DEV_FB_USED_PERCENT",
        "_temperature_c": "DCGM_FI_DEV_GPU_TEMP",
        "_memory_temperature_c": "DCGM_FI_DEV_MEMORY_TEMP",
        "_power_watts": "DCGM_FI_DEV_POWER_USAGE",
        "_energy_mj": "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION",
        "_mem_copy_util_percent": "DCGM_FI_DEV_MEM_COPY_UTIL",
        "_sm_clock_mhz": "DCGM_FI_DEV_SM_CLOCK",
        "_mem_clock_mhz": "DCGM_FI_DEV_MEM_CLOCK",
        "_pstate": "DCGM_FI_DEV_PSTATE",
        "_power_violation_ns": "DCGM_FI_DEV_POWER_VIOLATION",
        "_thermal_violation_ns": "DCGM_FI_DEV_THERMAL_VIOLATION",
        "_pcie_tx_throughput": "DCGM_FI_DEV_PCIE_TX_THROUGHPUT",
        "_pcie_rx_throughput": "DCGM_FI_DEV_PCIE_RX_THROUGHPUT",
        "_pcie_replay_counter": "DCGM_FI_DEV_PCIE_REPLAY_COUNTER",
        "_pcie_link_gen": "DCGM_FI_DEV_PCIE_LINK_GEN",
        "_pcie_link_width": "DCGM_FI_DEV_PCIE_LINK_WIDTH",
    }

    gpu_records: Dict[str, Dict[str, Any]] = {}

    def upsert_gpu_metric(metric_expr: str, field_name: str):
        if field_name == "_fb_total_mib":
            result = vm_query_optional(f'{metric_expr}{{kubernetes_node="{target_k8s_node}"}}')
            if not result:
                result = vm_query_optional(f'{metric_expr}{{Hostname="{target_host}"}}')
        else:
            result = vm_query_optional(f'{metric_expr}{{Hostname="{target_host}"}}')
        for item in result:
            m = item.get("metric", {})
            key = m.get("UUID") or m.get("gpu") or m.get("device") or m.get("instance")
            if not key:
                continue
            rec = gpu_records.setdefault(key, {
                "gpu": m.get("gpu"),
                "uuid": m.get("UUID"),
                "device": m.get("device"),
                "model_name": m.get("modelName"),
                "pci_bus_id": m.get("pci_bus_id"),
                "driver_version": m.get("DCGM_FI_DRIVER_VERSION"),
                "_utilization_percent": None,
                "_fb_total_mib": None,
                "_fb_used_mib": None,
                "_fb_free_mib": None,
                "_fb_reserved_mib": None,
                "_fb_used_percent": None,
                "_temperature_c": None,
                "_memory_temperature_c": None,
                "_power_watts": None,
                "_energy_mj": None,
                "_mem_copy_util_percent": None,
                "_sm_clock_mhz": None,
                "_mem_clock_mhz": None,
                "_pstate": None,
                "_power_violation_ns": None,
                "_thermal_violation_ns": None,
                "_pcie_tx_throughput": None,
                "_pcie_rx_throughput": None,
                "_pcie_replay_counter": None,
                "_pcie_link_gen": None,
                "_pcie_link_width": None,
                "_observed_fields": set(),
            })
            value = first_value_optional([item])
            rec[field_name] = value
            if value is not None:
                rec["_observed_fields"].add(field_name)

    for field_name, metric_expr in dcgm_fields.items():
        upsert_gpu_metric(metric_expr, field_name)

    for _key, rec in gpu_records.items():
        if rec.get("_fb_total_mib") is None:
            used = rec.get("_fb_used_mib")
            free = rec.get("_fb_free_mib")
            reserved = rec.get("_fb_reserved_mib")
            if used is not None and free is not None and reserved is not None:
                rec["_fb_total_mib"] = float(used) + float(free) + float(reserved)
        rec["_fb_used_percent"] = normalize_percent_value(rec.get("_fb_used_percent"))

    gpu_missing_by_gpu = []
    all_missing_counter: Dict[str, int] = {}
    for _key, rec in gpu_records.items():
        missing = []
        observed_fields = rec.get("_observed_fields", set())
        for internal_key, metric_name in GPU_FIELD_DEBUG_MAP.items():
            if internal_key not in observed_fields:
                missing.append(metric_name)
                all_missing_counter[metric_name] = all_missing_counter.get(metric_name, 0) + 1
        gpu_missing_by_gpu.append({
            "gpu": rec.get("gpu"),
            "uuid": rec.get("uuid"),
            "model_name": rec.get("model_name"),
            "missing_fields": missing,
        })

    gpu_missing_on_all = []
    gpu_count_for_debug = len(gpu_records)
    if gpu_count_for_debug > 0:
        gpu_missing_on_all = sorted([
            metric_name
            for metric_name, cnt in all_missing_counter.items()
            if cnt == gpu_count_for_debug
        ])

    cluster_gpu_nodes = safe_int(first_value(vm_query_optional(
        'count(count by (kubernetes_node) (DCGM_FI_DEV_GPU_UTIL))'
    ), 0.0), 0)
    cluster_gpu_total = safe_int(first_value(vm_query_optional(
        'count(DCGM_FI_DEV_GPU_UTIL)'
    ), 0.0), 0)

    cluster_gpu_capacity = safe_int(first_value(vm_query_optional(
        'sum(kube_node_status_capacity{resource="nvidia_com_gpu"})'
    ), 0.0), 0)
    cluster_gpu_allocatable = safe_int(first_value(vm_query_optional(
        'sum(kube_node_status_allocatable{resource="nvidia_com_gpu"})'
    ), 0.0), 0)
    target_gpu_capacity = safe_int(first_value(vm_query_optional(
        f'sum(kube_node_status_capacity{{node="{target_k8s_node}",resource="nvidia_com_gpu"}})'
    ), 0.0), 0)
    target_gpu_allocatable = safe_int(first_value(vm_query_optional(
        f'sum(kube_node_status_allocatable{{node="{target_k8s_node}",resource="nvidia_com_gpu"}})'
    ), 0.0), 0)

    gpu_workload_fb_vec = vm_query_optional(
        'sum by (namespace, pod) (DCGM_FI_DEV_FB_USED{namespace!="",pod!=""})'
    )
    gpu_workloads = []
    for item in gpu_workload_fb_vec:
        m = item.get("metric", {})
        ns = m.get("namespace")
        pod = m.get("pod")
        if not ns or not pod:
            continue
        fb_used_mib = first_value_optional([item])
        gpu_workloads.append({
            "namespace": ns,
            "pod": pod,
            "fb_used_bytes": mib_to_bytes(fb_used_mib),
        })

    gpu_workload_map = build_gpu_workload_map(gpu_workloads, target_namespace)
    gpu_workload_pods = gpu_workload_pod_names(gpu_workloads, target_namespace)
    ns_gpu_fb_used_bytes = sum(int(item["fb_used_bytes"] or 0) for item in gpu_workloads if item.get("namespace") == target_namespace)
    ns_gpu_pods = sum(1 for item in gpu_workloads if item.get("namespace") == target_namespace)

    total_gpu_fb_used_bytes = sum(int(mib_to_bytes(rec.get("_fb_used_mib")) or 0) for rec in gpu_records.values())
    fb_total_bytes_vals = [mib_to_bytes(rec.get("_fb_total_mib")) for rec in gpu_records.values() if mib_to_bytes(rec.get("_fb_total_mib")) is not None]
    gpu_fb_total_bytes = sum(int(v) for v in fb_total_bytes_vals) if fb_total_bytes_vals else None
    fb_free_bytes_vals = [mib_to_bytes(rec.get("_fb_free_mib")) for rec in gpu_records.values() if mib_to_bytes(rec.get("_fb_free_mib")) is not None]
    gpu_fb_free_bytes_min = min_non_none(fb_free_bytes_vals)

    gpu_list = []
    for _key, rec in sorted(gpu_records.items(), key=lambda kv: (str(kv[1].get("gpu") or ""), kv[0])):
        rec_out = {
            "gpu": rec.get("gpu"),
            "uuid": rec.get("uuid"),
            "device": rec.get("device"),
            "model_name": rec.get("model_name"),
            "pci_bus_id": rec.get("pci_bus_id"),
            "driver_version": rec.get("driver_version"),
            "utilization_percent": rec.get("_utilization_percent"),
            "fb_total_bytes": mib_to_bytes(rec.get("_fb_total_mib")),
            "fb_used_bytes": mib_to_bytes(rec.get("_fb_used_mib")),
            "fb_free_bytes": mib_to_bytes(rec.get("_fb_free_mib")),
            "fb_reserved_bytes": mib_to_bytes(rec.get("_fb_reserved_mib")),
            "fb_used_percent": rec.get("_fb_used_percent"),
            "temperature_c": rec.get("_temperature_c"),
            "memory_temperature_c": rec.get("_memory_temperature_c"),
            "power_watts": rec.get("_power_watts"),
            "energy_mj": rec.get("_energy_mj"),
            "mem_copy_util_percent": rec.get("_mem_copy_util_percent"),
            "sm_clock_mhz": rec.get("_sm_clock_mhz"),
            "mem_clock_mhz": rec.get("_mem_clock_mhz"),
            "pstate": rec.get("_pstate"),
            "power_violation_ns": rec.get("_power_violation_ns"),
            "thermal_violation_ns": rec.get("_thermal_violation_ns"),
            "pcie_tx_throughput": rec.get("_pcie_tx_throughput"),
            "pcie_rx_throughput": rec.get("_pcie_rx_throughput"),
            "pcie_replay_counter": rec.get("_pcie_replay_counter"),
            "pcie_link_gen": rec.get("_pcie_link_gen"),
            "pcie_link_width": rec.get("_pcie_link_width"),
        }
        gpu_list.append(rec_out)

    node_gpu_count = len(gpu_list)

    gpu_util_avg = avg_non_none([g.get("utilization_percent") for g in gpu_list])
    gpu_power_avg = avg_non_none([g.get("power_watts") for g in gpu_list])
    gpu_energy_sum_mj = sum(float(g.get("energy_mj") or 0.0) for g in gpu_list) if gpu_list else None

    gpu_fb_used_pct_avg = avg_non_none([g.get("fb_used_percent") for g in gpu_list])
    gpu_fb_used_pct_max = max_non_none([g.get("fb_used_percent") for g in gpu_list])

    gpu_mem_copy_util_avg = avg_non_none([g.get("mem_copy_util_percent") for g in gpu_list])

    gpu_temp_avg = avg_non_none([g.get("temperature_c") for g in gpu_list])
    gpu_mem_temp_avg = avg_non_none([g.get("memory_temperature_c") for g in gpu_list])

    gpu_sm_clock_avg = avg_non_none([g.get("sm_clock_mhz") for g in gpu_list])
    gpu_mem_clock_avg = avg_non_none([g.get("mem_clock_mhz") for g in gpu_list])
    gpu_pstate_avg = avg_non_none([g.get("pstate") for g in gpu_list])
    gpu_pstate_min = min_non_none([g.get("pstate") for g in gpu_list])

    gpu_power_violation_sum = sum(float(g.get("power_violation_ns") or 0.0) for g in gpu_list)
    gpu_thermal_violation_sum = sum(float(g.get("thermal_violation_ns") or 0.0) for g in gpu_list)

    gpu_pcie_tx_avg = avg_non_none([g.get("pcie_tx_throughput") for g in gpu_list])
    gpu_pcie_rx_avg = avg_non_none([g.get("pcie_rx_throughput") for g in gpu_list])
    gpu_pcie_replay_sum = sum(float(g.get("pcie_replay_counter") or 0.0) for g in gpu_list)
    gpu_pcie_link_gen_avg = avg_non_none([g.get("pcie_link_gen") for g in gpu_list])
    gpu_pcie_link_width_avg = avg_non_none([g.get("pcie_link_width") for g in gpu_list])

    phase_vec = vm_query_optional(
        f'sum by (phase) (kube_pod_status_phase{{namespace="{target_namespace}"}} == 1)'
    )
    pods_phase_counts: Dict[str, int] = {}
    for item in phase_vec:
        phase = item.get("metric", {}).get("phase")
        value = safe_int(item.get("value", [None, 0])[1], 0) or 0
        if phase:
            pods_phase_counts[phase] = value
    for k in ["Pending", "Running", "Succeeded", "Failed", "Unknown"]:
        pods_phase_counts.setdefault(k, 0)

    dep_desired_map = vector_to_map(vm_query_optional(
        f'kube_deployment_spec_replicas{{namespace="{target_namespace}"}}'
    ), "deployment")
    dep_ready_map = vector_to_map(vm_query_optional(
        f'kube_deployment_status_replicas_ready{{namespace="{target_namespace}"}}'
    ), "deployment")
    if not dep_ready_map:
        dep_ready_map = vector_to_map(vm_query_optional(
            f'kube_deployment_status_replicas_available{{namespace="{target_namespace}"}}'
        ), "deployment")

    deployments = []
    all_dep_ok = True
    deployment_managed_pods = set()

    pod_cpu_map = {}
    pod_mem_map = {}
    pod_ready_map = {}
    pod_node_map = {}

    if MODE == "fast":
        pod_cpu_map = vector_to_map(vm_query_optional(
            f'sum by(pod) (rate(container_cpu_usage_seconds_total{{{CADVISOR_SELECTOR},namespace="{target_namespace}",container!="",pod!=""}}[{RATE_WINDOW}]))'
        ), "pod")
        pod_mem_map = vector_to_map(vm_query_optional(
            f'sum by(pod) (container_memory_working_set_bytes{{{CADVISOR_SELECTOR},namespace="{target_namespace}",container!="",pod!=""}})'
        ), "pod")
        pod_ready_map = vector_to_map(vm_query_optional(
            f'max by(pod) (kube_pod_status_ready{{namespace="{target_namespace}",condition="true"}} == 1)'
        ), "pod")
        for item in vm_query_optional(f'kube_pod_info{{namespace="{target_namespace}"}}'):
            m = item.get("metric", {})
            p = m.get("pod")
            n = m.get("node")
            if p and n:
                pod_node_map[p] = n

    for dep_name, desired in sorted(dep_desired_map.items()):
        desired_i = safe_int(desired, 0) or 0
        ready_i = safe_int(dep_ready_map.get(dep_name, 0), 0) or 0

        rs_candidate_names = set()
        for item in vm_query_optional(
            f'kube_replicaset_owner{{namespace="{target_namespace}",owner_kind="Deployment",owner_is_controller="true",owner_name="{dep_name}"}}'
        ):
            rs = item.get("metric", {}).get("replicaset")
            if rs:
                rs_candidate_names.add(rs)

        active_rs_names = set()
        for rs in sorted(rs_candidate_names):
            rs_status = safe_int(first_value(vm_query_optional(
                f'kube_replicaset_status_replicas{{namespace="{target_namespace}",replicaset="{rs}"}}'
            ), 0.0), 0) or 0
            rs_spec = safe_int(first_value(vm_query_optional(
                f'kube_replicaset_spec_replicas{{namespace="{target_namespace}",replicaset="{rs}"}}'
            ), 0.0), 0) or 0
            if rs_status > 0 or rs_spec > 0:
                active_rs_names.add(rs)

        pod_names = set()
        for rs in sorted(active_rs_names):
            for item in vm_query_optional(
                f'kube_pod_owner{{namespace="{target_namespace}",owner_kind="ReplicaSet",owner_name="{rs}"}}'
            ):
                p = item.get("metric", {}).get("pod")
                if p:
                    pod_names.add(p)
        pod_names = sorted(pod_names)
        for p in pod_names:
            deployment_managed_pods.add(p)

        dep_cpu_sum = 0.0
        dep_mem_sum = 0.0
        pods = []

        for p in pod_names:
            if MODE == "fast":
                cpu = float(pod_cpu_map.get(p, 0.0))
                mem = float(pod_mem_map.get(p, 0.0))
                ready = float(pod_ready_map.get(p, 0.0)) >= 1.0
                node = pod_node_map.get(p, target_host)
            else:
                info_vec = vm_query_optional(f'kube_pod_info{{namespace="{target_namespace}",pod="{p}"}}')
                node = info_vec[0].get("metric", {}).get("node", target_host) if info_vec else target_host
                cpu = first_value(vm_query_optional(
                    f'avg_over_time((sum(rate(container_cpu_usage_seconds_total{{{CADVISOR_SELECTOR},namespace="{target_namespace}",pod="{p}",container!=""}}[{RATE_WINDOW}])))'
                    f'[{SMOOTH_WINDOW}:])'
                ), 0.0)
                mem = first_value(vm_query_optional(
                    f'sum(container_memory_working_set_bytes{{{CADVISOR_SELECTOR},namespace="{target_namespace}",pod="{p}",container!=""}})'
                ), 0.0)
                ready = first_value(vm_query_optional(
                    f'max(kube_pod_status_ready{{namespace="{target_namespace}",pod="{p}",condition="true"}} == 1)'
                ), 0.0) >= 1.0

            dep_cpu_sum += cpu or 0.0
            dep_mem_sum += mem or 0.0

            pods.append({
                "name": p,
                "node": node,
                "cpu_cores_rate": cpu,
                "memory_working_set_bytes": safe_int(mem, 0) or 0,
                "ready": bool(ready),
                "gpu": gpu_workload_map.get(p, default_gpu_info()),
            })

        dep_ok = (desired_i == 0) or (ready_i >= desired_i)
        all_dep_ok = all_dep_ok and dep_ok

        deployments.append({
            "name": dep_name,
            "replicas_desired": desired_i,
            "replicas_ready": ready_i,
            "cpu_cores_rate": dep_cpu_sum,
            "memory_working_set_bytes": safe_int(dep_mem_sum, 0) or 0,
            "pods": pods,
        })

    standalone_pods = []
    all_ns_pod_node_map = {}
    for item in vm_query_optional(f'kube_pod_info{{namespace="{target_namespace}"}}'):
        m = item.get("metric", {})
        p = m.get("pod")
        n = m.get("node")
        if p and n:
            all_ns_pod_node_map[p] = n

    all_ns_pod_ready_map = vector_to_map(vm_query_optional(
        f'max by(pod) (kube_pod_status_ready{{namespace="{target_namespace}",condition="true"}} == 1)'
    ), "pod")
    all_ns_pod_cpu_map = vector_to_map(vm_query_optional(
        f'sum by(pod) (rate(container_cpu_usage_seconds_total{{{CADVISOR_SELECTOR},namespace="{target_namespace}",container!="",pod!=""}}[{RATE_WINDOW}]))'
    ), "pod")
    all_ns_pod_mem_map = vector_to_map(vm_query_optional(
        f'sum by(pod) (container_memory_working_set_bytes{{{CADVISOR_SELECTOR},namespace="{target_namespace}",container!="",pod!=""}})'
    ), "pod")

    for p, node in sorted(all_ns_pod_node_map.items()):
        if p in deployment_managed_pods:
            continue
        standalone_pods.append({
            "name": p,
            "node": node,
            "cpu_cores_rate": float(all_ns_pod_cpu_map.get(p, 0.0)),
            "memory_working_set_bytes": safe_int(all_ns_pod_mem_map.get(p, 0.0), 0) or 0,
            "ready": float(all_ns_pod_ready_map.get(p, 0.0)) >= 1.0,
            "gpu": gpu_workload_map.get(p, default_gpu_info()),
        })

    output = {
        "schema": "intentcontinuum.state.v6",
        "meta": {
            "ts": ts,
            "observer": OBSERVER,
            "target_node": target_k8s_node,
            "target_host": target_host,
            "namespace": target_namespace,
        },
        "cluster_semantic": {
            "namespace_total": {
                "cpu_cores_rate": ns_cpu,
                "memory_working_set_bytes": safe_int(ns_mem, 0) or 0,
                "pods_running": ns_running,
                "pods_ready": ns_ready,
                "gpu_fb_used_bytes": ns_gpu_fb_used_bytes,
                "gpu_pods": ns_gpu_pods,
            },
            "pods_phase_counts": pods_phase_counts,
            "deployments": deployments,
            "standalone_pods": standalone_pods,
            "rate_ready": (ns_running > 0 and ns_ready >= ns_running and all_dep_ok),
            "gpu_inventory": {
                "source": "dcgm_exporter+k8s",
                "nodes_with_gpu": cluster_gpu_nodes,
                "observed_gpus": cluster_gpu_total,
                "capacity_gpus": cluster_gpu_capacity,
                "allocatable_gpus": cluster_gpu_allocatable,
            },
            "gpu_workloads": gpu_workloads,
            "gpu_workload_pods": gpu_workload_pods,
        },
        "target_node_semantic": {
            "node_pressure": {
                "cpu_usage_percent": node_metrics.get("cpu_usage_percent"),
                "memory_usage_percent": node_metrics.get("memory_usage_percent"),
                "disk_root_usage_percent": node_metrics.get("disk_root_usage_percent"),
            },
            "node_compute_features": {
                "source": "victoriametrics+node_exporter+netdata",
                "cpu_compute": {
                    "source": "victoriametrics+node_exporter+netdata",
                    "cpu_usage_percent": node_metrics.get("cpu_usage_percent"),
                    "cpu_cores_total": node_cpu_cores_total,
                    "cpu_used_cores": (
                        node_metrics.get("cpu_usage_percent") * node_cpu_cores_total / 100.0
                        if (node_metrics.get("cpu_usage_percent") is not None and node_cpu_cores_total is not None)
                        else None
                    ),
                    "load1": node_metrics.get("load1"),
                    "load5": node_metrics.get("load5"),
                    "load15": node_metrics.get("load15"),
                    "cpu_pressure_waiting_seconds_per_s": node_metrics.get("cpu_pressure_waiting_seconds_per_s"),
                    "schedstat_running_seconds_per_s": node_metrics.get("schedstat_running_seconds_per_s"),
                    "schedstat_waiting_seconds_per_s": node_metrics.get("schedstat_waiting_seconds_per_s"),
                    "schedstat_timeslices_per_s": node_metrics.get("schedstat_timeslices_per_s"),
                    "perf_cpu_cycles": node_metrics.get("perf_cpu_cycles"),
                    "perf_instructions": node_metrics.get("perf_instructions"),
                    "perf_instructions_per_cycle": node_metrics.get("perf_instructions_per_cycle"),
                    "perf_stalled_cycles": node_metrics.get("perf_stalled_cycles"),
                    "perf_branch_instructions": node_metrics.get("perf_branch_instructions"),
                    "perf_branch_misses": node_metrics.get("perf_branch_misses"),
                    "perf_cache_bpu_read_hits": node_metrics.get("perf_cache_bpu_read_hits"),
                    "perf_cache_bpu_read_misses": node_metrics.get("perf_cache_bpu_read_misses"),
                    "perf_cache_l1d_read_hits": node_metrics.get("perf_cache_l1d_read_hits"),
                    "perf_cache_l1d_read_misses": node_metrics.get("perf_cache_l1d_read_misses"),
                    "perf_cache_l1d_write_hits": node_metrics.get("perf_cache_l1d_write_hits"),
                    "perf_event_paranoid": node_metrics.get("perf_event_paranoid"),
                },
                "ram_capacity": {
                    "source": "victoriametrics+node_exporter+netdata",
                    "mem_available_bytes": safe_int(node_metrics.get("mem_available_bytes"), None),
                    "mem_total_bytes": node_memory_total_bytes,
                    "swap_used_bytes": node_metrics.get("swap_used_bytes"),
                    "swap_total_bytes": node_metrics.get("swap_total_bytes"),
                    "swap_free_bytes": node_metrics.get("swap_free_bytes"),
                    "memory_usage_percent": node_metrics.get("memory_usage_percent"),
                    "pgmajfault_per_s": node_metrics.get("pgmajfault_per_s"),
                    "pswpin_pages_per_s": node_metrics.get("pswpin_pages_per_s"),
                    "pswpout_pages_per_s": node_metrics.get("pswpout_pages_per_s"),
                    "memory_pressure_waiting_seconds_per_s": node_metrics.get("memory_pressure_waiting_seconds_per_s"),
                    "memory_pressure_stalled_seconds_per_s": node_metrics.get("memory_pressure_stalled_seconds_per_s"),
                },
                "data_movement": {
                    "source": "victoriametrics+node_exporter",
                    "disk_read_bytes_per_s": node_metrics.get("disk_read_bytes_per_s"),
                    "disk_write_bytes_per_s": node_metrics.get("disk_write_bytes_per_s"),
                    "network_receive_bytes_per_s": node_metrics.get("network_receive_bytes_per_s"),
                    "network_transmit_bytes_per_s": node_metrics.get("network_transmit_bytes_per_s"),
                    "io_pressure_waiting_seconds_per_s": node_metrics.get("io_pressure_waiting_seconds_per_s"),
                    "io_pressure_stalled_seconds_per_s": node_metrics.get("io_pressure_stalled_seconds_per_s"),
                },
            },
            "gpu_pressure": {
                "source": "dcgm_exporter+k8s",
                "status": "ok" if node_gpu_count > 0 else "no_gpu_or_not_observed",
                "gpu_count": node_gpu_count,
                "capacity_gpus": target_gpu_capacity,
                "allocatable_gpus": target_gpu_allocatable,
                "schedulable_gpu": target_gpu_allocatable > 0,
                "fb_used_total_bytes": total_gpu_fb_used_bytes if node_gpu_count > 0 else 0,
                "gpus": gpu_list,
            },
            "gpu_bound_features": {
                "gpu_compute": {
                    "gpu_util_avg": gpu_util_avg,
                    "sm_clock_mhz_avg": gpu_sm_clock_avg,
                    "mem_clock_mhz_avg": gpu_mem_clock_avg,
                    "power_watts_avg": gpu_power_avg,
                    "energy_mj_sum": gpu_energy_sum_mj,
                    "pstate_avg": gpu_pstate_avg,
                    "pstate_min": gpu_pstate_min,
                    "gpu_temp_avg": gpu_temp_avg,
                    "power_violation_ns_sum": gpu_power_violation_sum,
                    "thermal_violation_ns_sum": gpu_thermal_violation_sum,
                },
                "vram_capacity": {
                    "fb_total_bytes": gpu_fb_total_bytes,
                    "fb_used_total_bytes": total_gpu_fb_used_bytes if node_gpu_count > 0 else 0,
                    "fb_used_percent_avg": gpu_fb_used_pct_avg,
                    "fb_used_percent_max": gpu_fb_used_pct_max,
                    "fb_free_bytes_min": gpu_fb_free_bytes_min,
                    "memory_temp_avg": gpu_mem_temp_avg,
                },
                "data_movement": {
                    "mem_copy_util_percent_avg": gpu_mem_copy_util_avg,
                    "pcie_tx_throughput_avg": gpu_pcie_tx_avg,
                    "pcie_rx_throughput_avg": gpu_pcie_rx_avg,
                    "pcie_replay_counter_sum": gpu_pcie_replay_sum,
                    "pcie_link_gen_avg": gpu_pcie_link_gen_avg,
                    "pcie_link_width_avg": gpu_pcie_link_width_avg,
                },
            },
        },
        "_debug": {
            "mode": MODE,
            "observer": OBSERVER,
            "node_cpu_cores_total": node_cpu_cores_total,
            "node_memory_total_bytes": node_memory_total_bytes,
            "netdata_host_resolved": resolved_netdata_host,
            "identity_consistency": build_identity_debug(
                observer=OBSERVER,
                target_host=target_host,
                target_k8s_node=target_k8s_node,
                node_exporter_instance=node_exporter_instance,
                resolved_netdata_host=resolved_netdata_host,
            ),
        },
    }

    if netdata_host_scoped is not None:
        output = apply_netdata_overlay(output, netdata_host_scoped, resolved_netdata_host)
    else:
        output.setdefault("_debug", {})
        output["_debug"]["netdata_init_error"] = netdata_init_error
        output["_debug"]["netdata_overlay_skipped_reason"] = "netdata_parent_unreachable"

    output["_debug"]["node_exporter_instance"] = node_exporter_instance
    output["_debug"]["node_exporter_match_method"] = node_exporter_match_method
    output["_debug"]["gpu_series_found"] = len(gpu_list)
    output["_debug"]["cluster_gpu_nodes"] = cluster_gpu_nodes
    output["_debug"]["cluster_gpu_total"] = cluster_gpu_total
    output["_debug"]["cluster_gpu_capacity"] = cluster_gpu_capacity
    output["_debug"]["cluster_gpu_allocatable"] = cluster_gpu_allocatable
    output["_debug"]["target_gpu_capacity"] = target_gpu_capacity
    output["_debug"]["target_gpu_allocatable"] = target_gpu_allocatable
    output["_debug"]["gpu_workloads_found"] = len(gpu_workloads)
    output["_debug"]["gpu_workload_pods"] = gpu_workload_pods
    output["_debug"]["gpu_workload_map_keys"] = sorted(list(gpu_workload_map.keys()))
    output["_debug"]["namespace_gpu_pods"] = ns_gpu_pods
    output["_debug"]["namespace_gpu_fb_used_bytes"] = ns_gpu_fb_used_bytes
    output["_debug"]["deployment_managed_pods"] = sorted(list(deployment_managed_pods))
    output["_debug"]["standalone_pods_found"] = len(standalone_pods)
    output["_debug"]["k8s_node"] = target_k8s_node
    output["_debug"]["target_host"] = target_host
    output["_debug"]["cadvisor_selector"] = CADVISOR_SELECTOR
    output["_debug"]["vm_query_count"] = QCOUNT
    output["_debug"]["gpu_missing_fields"] = {
        "by_gpu": gpu_missing_by_gpu,
        "missing_on_all_gpus": gpu_missing_on_all,
    }

    return prune_none(output)


def collect_state():
    return collect_state_for_node(
        node_name=NODE,
        namespace=NAMESPACE,
        k8s_node_name=os.getenv("K8S_NODE", "").strip() or None,
    )


def build_error_state(exc: Exception) -> dict:
    target_host = clean_name(NODE or OBSERVER)
    target_k8s_node = canonical_k8s_node_name(os.getenv("K8S_NODE", "").strip() or target_host)
    target_namespace = clean_name(NAMESPACE)
    tb = traceback.format_exc().strip()
    if len(tb) > 4000:
        tb = f"{tb[:2000]}\n...<truncated>...\n{tb[-2000:]}"

    return {
        "schema": "intentcontinuum.state.v6",
        "collector_status": "error",
        "collector_error": f"{type(exc).__name__}: {exc}",
        "meta": {
            "ts": int(time.time()),
            "observer": OBSERVER,
            "target_node": target_k8s_node,
            "target_host": target_host,
            "namespace": target_namespace,
        },
        "_debug": {
            "mode": MODE,
            "observer": OBSERVER,
            "vm_url": VM_URL,
            "vm_query_count": QCOUNT,
            "node_exporter_instance": NODE_EXPORTER_INSTANCE,
            "node_exporter_match_method": "env_override" if NODE_EXPORTER_INSTANCE else "",
            "target_host": target_host,
            "k8s_node": target_k8s_node,
            "cadvisor_selector": CADVISOR_SELECTOR,
            "traceback": tb,
        },
    }


def main():
    try:
        data = collect_state()
        data.setdefault("collector_status", "ok")
        data.setdefault("collector_error", "")
    except Exception as e:
        data = build_error_state(e)

    if not DEBUG_OUTPUT:
        data.pop("_debug", None)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
