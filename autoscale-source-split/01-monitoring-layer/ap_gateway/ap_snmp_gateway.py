#!/usr/bin/env python3
import os
import re
import time
import subprocess
import shutil
import urllib.request
import importlib

OPENWRT = os.getenv("OPENWRT", "100.101.18.10")
AP_NAME = os.getenv("AP_NAME", "openwrt_ap")
AP_IFACE = os.getenv("AP_IFACE", "phy0-ap0")
SNMP_COMMUNITY = os.getenv("SNMP_COMMUNITY", "public")
SNMP_IFINDEX = os.getenv("SNMP_IFINDEX", "3")
ROOT_STORAGE_INDEX = os.getenv("ROOT_STORAGE_INDEX", "35")
SNMP_TIMEOUT = float(os.getenv("SNMP_TIMEOUT", "3"))
SNMP_RETRIES = int(os.getenv("SNMP_RETRIES", "0"))
INTERVAL = int(os.getenv("INTERVAL", "10"))
VM_URL = os.getenv("VM_URL", "http://140.113.179.9:31888/api/v1/import/prometheus")

OIDS = {
    "load1": ".1.3.6.1.4.1.2021.10.1.6.1",
    "load5": ".1.3.6.1.4.1.2021.10.1.6.2",
    "load15": ".1.3.6.1.4.1.2021.10.1.6.3",

    "mem_total_kb": ".1.3.6.1.4.1.2021.4.5.0",
    "mem_available_kb": ".1.3.6.1.4.1.2021.4.6.0",
    "mem_buffer_kb": ".1.3.6.1.4.1.2021.4.14.0",
    "mem_cached_kb": ".1.3.6.1.4.1.2021.4.15.0",

    "swap_total_kb": ".1.3.6.1.4.1.2021.4.3.0",
    "swap_available_kb": ".1.3.6.1.4.1.2021.4.4.0",

    "cpu_user_percent": ".1.3.6.1.4.1.2021.11.9.0",
    "cpu_system_percent": ".1.3.6.1.4.1.2021.11.10.0",
    "cpu_idle_percent": ".1.3.6.1.4.1.2021.11.11.0",
    "cpu_num_cores": ".1.3.6.1.4.1.2021.11.67.0",

    # HOST-RESOURCES-MIB hrStorageTable entry for the root overlay filesystem.
    "root_disk_allocation_unit_bytes": f".1.3.6.1.2.1.25.2.3.1.4.{ROOT_STORAGE_INDEX}",
    "root_disk_size_units": f".1.3.6.1.2.1.25.2.3.1.5.{ROOT_STORAGE_INDEX}",
    "root_disk_used_units": f".1.3.6.1.2.1.25.2.3.1.6.{ROOT_STORAGE_INDEX}",

    "iface_rx_bytes_total": f".1.3.6.1.2.1.2.2.1.10.{SNMP_IFINDEX}",
    "iface_tx_bytes_total": f".1.3.6.1.2.1.2.2.1.16.{SNMP_IFINDEX}",
    "iface_rx_errors_total": f".1.3.6.1.2.1.2.2.1.14.{SNMP_IFINDEX}",
    "iface_tx_errors_total": f".1.3.6.1.2.1.2.2.1.20.{SNMP_IFINDEX}",
    "iface_admin_status": f".1.3.6.1.2.1.2.2.1.7.{SNMP_IFINDEX}",
    "iface_oper_status": f".1.3.6.1.2.1.2.2.1.8.{SNMP_IFINDEX}",
}


def parse_number(text):
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else None


def snmpget(oid):
    if shutil.which("snmpget"):
        try:
            return snmpget_cli(oid)
        except (subprocess.TimeoutExpired, RuntimeError):
            pass
    return snmpget_pysnmp(oid)


def snmpget_cli(oid):
    cmd = [
        "snmpget",
        "-v2c",
        "-c", SNMP_COMMUNITY,
        "-On",
        "-Oqv",
        "-m", "",
        OPENWRT,
        oid,
    ]
    r = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=SNMP_TIMEOUT + 2,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return parse_number(r.stdout.strip())


def snmpget_pysnmp(oid):
    try:
        hlapi = importlib.import_module("pysnmp.hlapi")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "snmpget command not found and pysnmp is not installed"
        ) from exc

    iterator = hlapi.getCmd(
        hlapi.SnmpEngine(),
        hlapi.CommunityData(SNMP_COMMUNITY, mpModel=1),
        hlapi.UdpTransportTarget((OPENWRT, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES),
        hlapi.ContextData(),
        hlapi.ObjectType(hlapi.ObjectIdentity(oid)),
    )
    error_indication, error_status, error_index, var_binds = next(iterator)
    if error_indication:
        raise RuntimeError(str(error_indication))
    if error_status:
        raise RuntimeError(
            f"{error_status.prettyPrint()} at {error_index and var_binds[int(error_index) - 1][0] or '?'}"
        )

    for _, value in var_binds:
        return parse_number(value.prettyPrint())
    return None


def metric(name, value, labels):
    label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
    return f'{name}{{{label_str}}} {value}'


def collect():
    values = {}
    for name, oid in OIDS.items():
        v = snmpget(oid)
        if v is not None:
            values[name] = v

    node_labels = {
        "ap": AP_NAME,
        "target": OPENWRT,
    }

    iface_labels = {
        "ap": AP_NAME,
        "target": OPENWRT,
        "iface": AP_IFACE,
        "ifindex": SNMP_IFINDEX,
    }

    mem_total = values.get("mem_total_kb", 0) * 1024
    mem_available = values.get("mem_available_kb", 0) * 1024
    mem_used = max(mem_total - mem_available, 0)
    mem_usage = (mem_used / mem_total * 100) if mem_total > 0 else 0

    root_disk_unit = values.get("root_disk_allocation_unit_bytes", 0)
    root_disk_size = values.get("root_disk_size_units", 0) * root_disk_unit
    root_disk_used = values.get("root_disk_used_units", 0) * root_disk_unit
    root_disk_available = max(root_disk_size - root_disk_used, 0)
    root_disk_usage = (root_disk_used / root_disk_size * 100) if root_disk_size > 0 else 0

    cpu_idle = values.get("cpu_idle_percent", 0)
    cpu_usage = max(100 - cpu_idle, 0)

    lines = []

    lines.append(metric("ap_node_load1", values.get("load1", 0), node_labels))
    lines.append(metric("ap_node_load5", values.get("load5", 0), node_labels))
    lines.append(metric("ap_node_load15", values.get("load15", 0), node_labels))

    lines.append(metric("ap_node_cpu_usage_percent", cpu_usage, node_labels))
    lines.append(metric("ap_node_cpu_idle_percent", cpu_idle, node_labels))
    lines.append(metric("ap_node_cpu_user_percent", values.get("cpu_user_percent", 0), node_labels))
    lines.append(metric("ap_node_cpu_system_percent", values.get("cpu_system_percent", 0), node_labels))
    lines.append(metric("ap_node_cpu_num_cores", values.get("cpu_num_cores", 0), node_labels))

    lines.append(metric("ap_node_memory_total_bytes", mem_total, node_labels))
    lines.append(metric("ap_node_memory_available_bytes", mem_available, node_labels))
    lines.append(metric("ap_node_memory_used_bytes", mem_used, node_labels))
    lines.append(metric("ap_node_memory_usage_percent", mem_usage, node_labels))
    lines.append(metric("ap_node_memory_buffer_bytes", values.get("mem_buffer_kb", 0) * 1024, node_labels))
    lines.append(metric("ap_node_memory_cached_bytes", values.get("mem_cached_kb", 0) * 1024, node_labels))

    lines.append(metric("ap_node_swap_total_bytes", values.get("swap_total_kb", 0) * 1024, node_labels))
    lines.append(metric("ap_node_swap_available_bytes", values.get("swap_available_kb", 0) * 1024, node_labels))

    lines.append(metric("ap_node_disk_root_size_bytes", root_disk_size, node_labels))
    lines.append(metric("ap_node_disk_root_used_bytes", root_disk_used, node_labels))
    lines.append(metric("ap_node_disk_root_available_bytes", root_disk_available, node_labels))
    lines.append(metric("ap_node_disk_root_usage_percent", root_disk_usage, node_labels))

    lines.append(metric("ap_node_iface_rx_bytes_total", values.get("iface_rx_bytes_total", 0), iface_labels))
    lines.append(metric("ap_node_iface_tx_bytes_total", values.get("iface_tx_bytes_total", 0), iface_labels))
    lines.append(metric("ap_node_iface_rx_errors_total", values.get("iface_rx_errors_total", 0), iface_labels))
    lines.append(metric("ap_node_iface_tx_errors_total", values.get("iface_tx_errors_total", 0), iface_labels))
    lines.append(metric("ap_node_iface_admin_status", values.get("iface_admin_status", 0), iface_labels))
    lines.append(metric("ap_node_iface_oper_status", values.get("iface_oper_status", 0), iface_labels))

    return "\n".join(lines) + "\n"


def push(payload):
    if not VM_URL:
        return
    req = urllib.request.Request(
        VM_URL,
        data=payload.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"VictoriaMetrics import failed: HTTP {resp.status}")


def main():
    while True:
        try:
            payload = collect()
            print(payload, end="", flush=True)
            push(payload)
        except Exception as e:
            print(f"[ap_snmp_gateway] error: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
