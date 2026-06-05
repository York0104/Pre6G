#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


NETDATA_URL = os.getenv("NETDATA_URL", "http://140.113.179.9:32163").rstrip("/")
NETDATA_HOST = os.getenv("NETDATA_HOST", "pynq").strip()
VM_URL = os.getenv("VM_URL", "http://140.113.179.9:31888").rstrip("/")
QUERY_TIMEOUT = float(os.getenv("QUERY_TIMEOUT", "5"))

JOB = os.getenv("JOB", "rfsoc4x2-node-exporter").strip()
ACCESS = os.getenv("ACCESS", "tailscale").strip()
BOARD = os.getenv("BOARD", "RFSoC4x2").strip()
DEVICE = os.getenv("DEVICE", BOARD).strip()
INSTANCE = os.getenv("INSTANCE", "100.91.37.32:9100").strip()
NODE_LABEL = os.getenv("NODE_LABEL", "rfsoc4x2-pynq").strip()
ROLE = os.getenv("ROLE", "external-rfsoc").strip()
LAB_IP = os.getenv("LAB_IP", "192.168.100.217").strip()
TAILSCALE_IP = os.getenv("TAILSCALE_IP", "100.91.37.32").strip()
OBSERVER = socket.gethostname()
PL_STATUS_SSH_TARGET = os.getenv("PL_STATUS_SSH_TARGET", "xilinx@100.91.37.32").strip()
PL_STATUS_SSH_KEY = os.getenv("PL_STATUS_SSH_KEY", "/home/icclz2/.ssh/id_ed25519_rfsoc").strip()
PL_STATUS_SSH_TIMEOUT = float(os.getenv("PL_STATUS_SSH_TIMEOUT", "3"))
PL_STATUS_REMOTE_CMD = os.getenv(
    "PL_STATUS_REMOTE_CMD",
    "cat /run/rfsoc_overlay_status.json",
).strip()

MIB_TO_BYTES = 1024 * 1024
KIB_TO_BYTES = 1024


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


def http_get_json(url: str) -> Any:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=QUERY_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def netdata_chart(chart: str) -> dict:
    url = (
        f"{NETDATA_URL}/host/{NETDATA_HOST}/api/v1/data?"
        + urllib.parse.urlencode({
            "chart": chart,
            "format": "json",
            "points": "1",
            "after": "-30",
        })
    )
    return http_get_json(url)


def latest_row_map(payload: dict) -> Dict[str, float]:
    labels = payload.get("labels") or []
    data = payload.get("data") or []
    if len(labels) < 2 or not data:
        return {}
    row = data[0]
    out: Dict[str, float] = {}
    for idx in range(1, min(len(labels), len(row))):
        try:
            out[str(labels[idx])] = float(row[idx])
        except Exception:
            continue
    return out


def chart_values(chart: str) -> Dict[str, float]:
    return latest_row_map(netdata_chart(chart))


def chart_value(chart: str, dim: str) -> Optional[float]:
    return chart_values(chart).get(dim)


def chart_sum(chart: str, dims: List[str]) -> float:
    values = chart_values(chart)
    total = 0.0
    for dim in dims:
        total += float(values.get(dim, 0.0))
    return total


def abs_or_none(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return abs(float(value))


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return default


def mib_to_bytes(value_mib: Optional[float]) -> Optional[int]:
    if value_mib is None:
        return None
    return int(float(value_mib) * MIB_TO_BYTES)


def kib_to_bytes_per_s(value_kib: Optional[float]) -> Optional[int]:
    if value_kib is None:
        return None
    return int(float(value_kib) * KIB_TO_BYTES)


def vm_query(promql: str) -> list:
    url = f"{VM_URL}/api/v1/query?" + urllib.parse.urlencode({"query": promql})
    payload = http_get_json(url)
    if payload.get("status") != "success":
        raise RuntimeError(f"VictoriaMetrics query failed: {payload}")
    return payload.get("data", {}).get("result", [])


def vm_first_value(promql: str, default: Optional[float] = None) -> Optional[float]:
    result = vm_query(promql)
    if not result:
        return default
    try:
        return float(result[0]["value"][1])
    except Exception:
        return default


def vm_bool_up(promql: str) -> Optional[bool]:
    value = vm_first_value(promql, default=None)
    if value is None:
        return None
    return value > 0


def to_int_flag(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return 1 if float(value) != 0 else 0

    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "ready", "loaded", "ok", "present"}:
        return 1
    return 0


def to_int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def extract_first(payload: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)
    return None


def parse_pl_status_output(raw: str) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    text = (raw or "").strip()

    if not text:
        raise ValueError("empty PL status output")

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            parsed = payload
    except Exception:
        parsed = {}

    normalized = {
        "source": "pynq+xrt",
        "xrt_device_ready": to_int_flag(
            extract_first(parsed, ["xrt_device_ready", "device_ready", "xrt_ready"])
        ),
        "overlay_loaded": to_int_flag(
            extract_first(parsed, ["overlay_loaded", "is_overlay_loaded", "loaded"])
        ),
        "active_bitfile": extract_first(parsed, ["active_bitfile", "bitfile", "bitstream"]),
        "ip_count": to_int_or_none(extract_first(parsed, ["ip_count", "ipcount", "ip_num"])),
        "has_rfdc": to_int_flag(extract_first(parsed, ["has_rfdc", "rfdc"])),
        "has_dma": to_int_flag(extract_first(parsed, ["has_dma", "dma"])),
        "has_sysmon": to_int_flag(extract_first(parsed, ["has_sysmon", "sysmon"])),
        "temperature_c": extract_first(parsed, ["temperature_c", "sysmon_temperature_c"]),
        "vccint_v": extract_first(parsed, ["vccint_v", "sysmon_vccint_v"]),
        "vccaux_v": extract_first(parsed, ["vccaux_v", "sysmon_vccaux_v"]),
    }

    if parsed:
        return normalized

    for line in text.splitlines():
        lower = line.strip().lower()
        if ":" in line:
            key, value = [part.strip() for part in line.split(":", 1)]
            key_lower = key.lower()
            if key_lower in {"active_bitfile", "bitfile", "bitstream"}:
                normalized["active_bitfile"] = value
            elif key_lower in {"ip_count", "ipcount", "ip_num"}:
                normalized["ip_count"] = to_int_or_none(value)
            elif key_lower in {"xrt_device_ready", "device_ready", "xrt_ready"}:
                normalized["xrt_device_ready"] = to_int_flag(value)
            elif key_lower in {"overlay_loaded", "is_overlay_loaded", "loaded"}:
                normalized["overlay_loaded"] = to_int_flag(value)
            elif key_lower in {"has_rfdc", "rfdc"}:
                normalized["has_rfdc"] = to_int_flag(value)
            elif key_lower in {"has_dma", "dma"}:
                normalized["has_dma"] = to_int_flag(value)
            elif key_lower in {"has_sysmon", "sysmon"}:
                normalized["has_sysmon"] = to_int_flag(value)
            elif key_lower in {"temperature_c", "sysmon_temperature_c"}:
                normalized["temperature_c"] = to_int_or_none(value) if value.isdigit() else None
                try:
                    normalized["temperature_c"] = float(value)
                except Exception:
                    pass
            elif key_lower in {"vccint_v", "sysmon_vccint_v"}:
                try:
                    normalized["vccint_v"] = float(value)
                except Exception:
                    pass
            elif key_lower in {"vccaux_v", "sysmon_vccaux_v"}:
                try:
                    normalized["vccaux_v"] = float(value)
                except Exception:
                    pass

        if "bit" in lower and normalized["active_bitfile"] is None:
            normalized["active_bitfile"] = line.strip()
        if "rfdc" in lower:
            normalized["has_rfdc"] = 1
        if "dma" in lower:
            normalized["has_dma"] = 1
        if "sysmon" in lower:
            normalized["has_sysmon"] = 1

    return normalized


def collect_pl_status() -> Dict[str, Any]:
    base = {
        "source": "pynq+xrt",
        "xrt_device_ready": 0,
        "overlay_loaded": 0,
        "active_bitfile": None,
        "ip_count": None,
        "has_rfdc": 0,
        "has_dma": 0,
        "has_sysmon": 0,
        "temperature_c": None,
        "vccint_v": None,
        "vccaux_v": None,
    }

    if not PL_STATUS_SSH_TARGET or not PL_STATUS_SSH_KEY or not PL_STATUS_REMOTE_CMD:
        return base

    try:
        cmd = [
            "ssh",
            "-i",
            PL_STATUS_SSH_KEY,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "StrictHostKeyChecking=accept-new",
            PL_STATUS_SSH_TARGET,
            PL_STATUS_REMOTE_CMD,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=PL_STATUS_SSH_TIMEOUT,
            check=True,
        )
        base.update(parse_pl_status_output(result.stdout))
    except Exception:
        return base

    return base


def build_vm_selector() -> str:
    return f'job="{JOB}",access="{ACCESS}",device="{DEVICE}",instance="{INSTANCE}"'


def collect_netdata_metrics() -> dict:
    cpu_dims = chart_values("system.cpu")
    cpu_user_percent = cpu_dims.get("user")
    cpu_system_percent = cpu_dims.get("system")
    cpu_idle_percent = cpu_dims.get("idle")
    cpu_iowait_percent = cpu_dims.get("iowait")
    if cpu_idle_percent is None and cpu_dims:
        used = sum(float(v) for v in cpu_dims.values() if v is not None)
        cpu_idle_percent = max(0.0, min(100.0, 100.0 - used))
    cpu_idle_percent = safe_float(cpu_idle_percent)
    cpu_usage_percent = chart_sum(
        "system.cpu",
        ["user", "system", "nice", "iowait", "irq", "softirq", "steal", "guest", "guest_nice"],
    )
    ram_used_mib = chart_value("system.ram", "used")
    ram_free_mib = chart_value("system.ram", "free")
    ram_cached_mib = chart_value("system.ram", "cached")
    ram_buffers_mib = chart_value("system.ram", "buffers")
    mem_available_mib = chart_value("mem.available", "avail")
    swap_free_mib = chart_value("mem.swap", "free")
    swap_used_mib = chart_value("mem.swap", "used")
    load1 = chart_value("system.load", "load1")
    load5 = chart_value("system.load", "load5")
    load15 = chart_value("system.load", "load15")
    disk_read_kib_per_s = chart_value("system.io", "reads")
    disk_write_kib_per_s = abs_or_none(chart_value("system.io", "writes"))
    eth0_rx_kilobits_per_sec = chart_value("net.eth0", "received")
    eth0_tx_kilobits_per_sec = abs_or_none(chart_value("net.eth0", "sent"))

    return {
        "cpu_usage_percent": cpu_usage_percent,
        "cpu_user_percent": cpu_user_percent,
        "cpu_system_percent": cpu_system_percent,
        "cpu_idle_percent": cpu_idle_percent,
        "cpu_iowait_percent": cpu_iowait_percent,
        "ram_used_mib": ram_used_mib,
        "ram_free_mib": ram_free_mib,
        "ram_cached_mib": ram_cached_mib,
        "ram_buffers_mib": ram_buffers_mib,
        "mem_available_mib": mem_available_mib,
        "swap_free_mib": swap_free_mib,
        "swap_used_mib": swap_used_mib,
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "disk_read_bytes_per_s": kib_to_bytes_per_s(disk_read_kib_per_s),
        "disk_write_bytes_per_s": kib_to_bytes_per_s(disk_write_kib_per_s),
        "eth0_rx_kilobits_per_sec": eth0_rx_kilobits_per_sec,
        "eth0_tx_kilobits_per_sec": eth0_tx_kilobits_per_sec,
        "node_memory_working_set_bytes": mib_to_bytes(ram_used_mib),
        "mem_used_bytes": mib_to_bytes(ram_used_mib),
        "mem_free_bytes": mib_to_bytes(ram_free_mib),
        "mem_available_bytes": mib_to_bytes(mem_available_mib),
        "swap_free_bytes": mib_to_bytes(swap_free_mib),
        "swap_used_bytes": mib_to_bytes(swap_used_mib),
    }


def collect_vm_metrics(selector: str) -> dict:
    return {
        "up": vm_bool_up(f"up{{{selector}}}"),
        "cpu_usage_percent": vm_first_value(
            f'100 * (1 - avg(rate(node_cpu_seconds_total{{{selector},mode="idle"}}[1m])))',
            default=None,
        ),
        "cpu_cores_total": vm_first_value(
            f"count(count by (cpu) (node_cpu_seconds_total{{{selector}}}))",
            default=None,
        ),
        "mem_available_bytes": vm_first_value(
            f"node_memory_MemAvailable_bytes{{{selector}}}",
            default=None,
        ),
        "mem_total_bytes": vm_first_value(
            f"node_memory_MemTotal_bytes{{{selector}}}",
            default=None,
        ),
        "mem_free_bytes": vm_first_value(
            f"node_memory_MemFree_bytes{{{selector}}}",
            default=None,
        ),
        "rootfs_available_bytes": vm_first_value(
            f'node_filesystem_avail_bytes{{{selector},mountpoint="/",fstype!~"tmpfs|overlay"}}',
            default=None,
        ),
        "rootfs_size_bytes": vm_first_value(
            f'node_filesystem_size_bytes{{{selector},mountpoint="/",fstype!~"tmpfs|overlay"}}',
            default=None,
        ),
        "rootfs_used_percent": vm_first_value(
            f'max(100 * (1 - (node_filesystem_avail_bytes{{{selector},mountpoint="/",fstype!~"tmpfs|overlay"}} / '
            f'node_filesystem_size_bytes{{{selector},mountpoint="/",fstype!~"tmpfs|overlay"}})))',
            default=None,
        ),
        "network_receive_bytes_per_s": vm_first_value(
            f'sum(rate(node_network_receive_bytes_total{{{selector},device!="lo"}}[1m]))',
            default=None,
        ),
        "network_transmit_bytes_per_s": vm_first_value(
            f'sum(rate(node_network_transmit_bytes_total{{{selector},device!="lo"}}[1m]))',
            default=None,
        ),
    }


def maybe_ratio_percent(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return 100.0 * float(numerator) / float(denominator)


def build_source_label(netdata_ok: bool, vm_ok: bool) -> str:
    parts: List[str] = []
    if netdata_ok:
        parts.append("netdata")
    if vm_ok:
        parts.append("victoriametrics")
        parts.append("node_exporter")
    if not parts:
        return "unavailable"
    seen = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return "+".join(seen)


def collect_state() -> dict:
    selector = build_vm_selector()
    debug_errors: Dict[str, str] = {}

    try:
        netdata = collect_netdata_metrics()
        netdata_ok = True
    except Exception as e:
        netdata = {}
        netdata_ok = False
        debug_errors["netdata_error"] = str(e)

    try:
        vm = collect_vm_metrics(selector)
        vm_ok = True
    except Exception as e:
        vm = {}
        vm_ok = False
        debug_errors["victoriametrics_error"] = str(e)

    pl_status = collect_pl_status()

    mem_total_bytes = vm.get("mem_total_bytes")
    mem_available_bytes = netdata.get("mem_available_bytes")
    if mem_available_bytes is None:
        mem_available_bytes = vm.get("mem_available_bytes")
    cpu_cores_total = vm.get("cpu_cores_total")
    cpu_usage_percent = netdata.get("cpu_usage_percent")
    if cpu_usage_percent is None:
        cpu_usage_percent = vm.get("cpu_usage_percent")

    memory_headroom_percent = maybe_ratio_percent(mem_available_bytes, mem_total_bytes)
    memory_usage_percent = None
    if memory_headroom_percent is not None:
        memory_usage_percent = 100.0 - memory_headroom_percent

    cpu_used_cores = None
    if cpu_usage_percent is not None and cpu_cores_total is not None:
        cpu_used_cores = float(cpu_usage_percent) * float(cpu_cores_total) / 100.0

    swap_total_bytes = None
    if netdata.get("swap_used_bytes") is not None and netdata.get("swap_free_bytes") is not None:
        swap_total_bytes = int(netdata["swap_used_bytes"] + netdata["swap_free_bytes"])

    mem_used_bytes = netdata.get("mem_used_bytes")
    if mem_used_bytes is None and mem_total_bytes is not None and mem_available_bytes is not None:
        mem_used_bytes = int(float(mem_total_bytes) - float(mem_available_bytes))

    mem_free_bytes = netdata.get("mem_free_bytes")
    if mem_free_bytes is None:
        mem_free_bytes = vm.get("mem_free_bytes")

    node_memory_working_set_bytes = netdata.get("node_memory_working_set_bytes")
    if node_memory_working_set_bytes is None:
        node_memory_working_set_bytes = mem_used_bytes

    load_per_core = None
    if netdata.get("load1") is not None and cpu_cores_total not in (None, 0):
        load_per_core = float(netdata["load1"]) / float(cpu_cores_total)

    source_label = build_source_label(netdata_ok, vm_ok)
    instant_status = "ok"
    if not netdata_ok and vm.get("up") is True:
        instant_status = "vm_only"
    elif netdata_ok and vm.get("up") is False:
        instant_status = "netdata_only"
    elif not netdata_ok and not vm_ok:
        instant_status = "partial_unavailable"

    return {
        "schema": "intentcontinuum.state.v6",
        "collector_status": "ok",
        "collector_error": "",
        "meta": {
            "ts": int(time.time()),
            "observer": OBSERVER,
            "target_node": NODE_LABEL,
            "target_host": NETDATA_HOST,
            "namespace": None,
        },
        "target_node_semantic": {
            "node_identity": {
                "board": BOARD,
                "role": ROLE,
                "access": ACCESS,
                "k8s_node": False,
                "instance": INSTANCE,
                "lab_ip": LAB_IP,
                "tailscale_ip": TAILSCALE_IP,
            },
            "pl_status": pl_status,
            "scheduling_capability": {
                "can_run_linux_task": True,
                "can_run_container_task": False,
                "can_run_fpga_overlay": True,
                "can_run_rfdc_pipeline": bool(pl_status.get("has_rfdc")),
                "can_run_dma_pipeline": bool(pl_status.get("has_dma")),
                "k8s_node": False,
            },
            "node_pressure": {
                "cpu_usage_percent": cpu_usage_percent,
                "memory_usage_percent": memory_usage_percent,
                "disk_root_usage_percent": vm.get("rootfs_used_percent"),
            },
            "node_pressure_instant": {
                "source": source_label,
                "scope": "host",
                "host": NETDATA_HOST,
                "update_every_s": 1,
                "window_s": 1,
                "status": instant_status if vm.get("up") is not False else "vm_up_down",
                "cpu_usage_percent": cpu_usage_percent,
                "cpu_user_percent": netdata.get("cpu_user_percent"),
                "cpu_system_percent": netdata.get("cpu_system_percent"),
                "cpu_idle_percent": netdata.get("cpu_idle_percent"),
                "cpu_iowait_percent": netdata.get("cpu_iowait_percent"),
                "memory_usage_percent": memory_usage_percent,
                "mem_total_bytes": mem_total_bytes,
                "node_memory_working_set_bytes": node_memory_working_set_bytes,
                "node_memory_used_bytes": node_memory_working_set_bytes,
                "mem_used_bytes": mem_used_bytes,
                "mem_free_bytes": mem_free_bytes,
                "mem_available_bytes": mem_available_bytes,
                "disk_root_usage_percent": vm.get("rootfs_used_percent"),
                "memory_capacity": {
                    "source": source_label,
                    "mem_available_bytes": mem_available_bytes,
                    "swap_used_bytes": netdata.get("swap_used_bytes"),
                    "swap_total_bytes": swap_total_bytes,
                    "swap_free_bytes": netdata.get("swap_free_bytes"),
                },
                "node_disk_io": {
                    "read_bytes_per_s": netdata.get("disk_read_bytes_per_s"),
                    "write_bytes_per_s": netdata.get("disk_write_bytes_per_s"),
                    "netdata_read_bytes_per_s": netdata.get("disk_read_bytes_per_s"),
                    "netdata_write_bytes_per_s": netdata.get("disk_write_bytes_per_s"),
                },
                "load_average": {
                    "load1": netdata.get("load1"),
                    "load5": netdata.get("load5"),
                    "load15": netdata.get("load15"),
                    "load_per_core": load_per_core,
                },
                "network": {
                    "eth0_rx_kilobits_per_sec": netdata.get("eth0_rx_kilobits_per_sec"),
                    "eth0_tx_kilobits_per_sec": netdata.get("eth0_tx_kilobits_per_sec"),
                },
            },
            "node_compute_features": {
                "source": source_label,
                "cpu_compute": {
                    "source": source_label,
                    "cpu_usage_percent": cpu_usage_percent,
                    "cpu_user_percent": netdata.get("cpu_user_percent"),
                    "cpu_system_percent": netdata.get("cpu_system_percent"),
                    "cpu_idle_percent": netdata.get("cpu_idle_percent"),
                    "cpu_iowait_percent": netdata.get("cpu_iowait_percent"),
                    "cpu_cores_total": cpu_cores_total,
                    "cpu_used_cores": cpu_used_cores,
                    "load1": netdata.get("load1"),
                    "load5": netdata.get("load5"),
                    "load15": netdata.get("load15"),
                    "load_per_core": load_per_core,
                },
                "ram_capacity": {
                    "source": source_label,
                    "mem_available_bytes": mem_available_bytes,
                    "mem_total_bytes": mem_total_bytes,
                    "mem_used_bytes": mem_used_bytes,
                    "mem_free_bytes": mem_free_bytes,
                    "swap_used_bytes": netdata.get("swap_used_bytes"),
                    "swap_total_bytes": swap_total_bytes,
                    "swap_free_bytes": netdata.get("swap_free_bytes"),
                    "memory_usage_percent": memory_usage_percent,
                    "memory_headroom_percent": memory_headroom_percent,
                    "ram_used_mib": netdata.get("ram_used_mib"),
                    "ram_free_mib": netdata.get("ram_free_mib"),
                    "ram_cached_mib": netdata.get("ram_cached_mib"),
                    "ram_buffers_mib": netdata.get("ram_buffers_mib"),
                    "mem_available_mib": netdata.get("mem_available_mib"),
                },
                "data_movement": {
                    "source": source_label,
                    "netdata_disk_read_bytes_per_s": netdata.get("disk_read_bytes_per_s"),
                    "netdata_disk_write_bytes_per_s": netdata.get("disk_write_bytes_per_s"),
                    "network_receive_kilobits_per_s": netdata.get("eth0_rx_kilobits_per_sec"),
                    "network_transmit_kilobits_per_s": netdata.get("eth0_tx_kilobits_per_sec"),
                    "network_receive_bytes_per_s": vm.get("network_receive_bytes_per_s"),
                    "network_transmit_bytes_per_s": vm.get("network_transmit_bytes_per_s"),
                    "rootfs_available_bytes": vm.get("rootfs_available_bytes"),
                    "rootfs_size_bytes": vm.get("rootfs_size_bytes"),
                    "rootfs_used_percent": vm.get("rootfs_used_percent"),
                },
            },
            "health": {
                "source": "victoriametrics",
                "up": vm.get("up"),
            },
        },
        "_debug": {
            "netdata_parent_url": NETDATA_URL,
            "netdata_host_resolved": NETDATA_HOST,
            "vm_url": VM_URL,
            "vm_selector": selector,
            "pl_status_ssh_target": PL_STATUS_SSH_TARGET,
            "eth0_tx_raw_sign": "netdata_sent_is_negative_by_design",
            "source_preference": {
                "instant": "netdata",
                "capacity": "victoriametrics",
            },
            **debug_errors,
        },
    }


def main() -> None:
    print(json.dumps(prune_none(collect_state()), indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
