#!/usr/bin/env python3
import os
import json
import time
import socket
import urllib.parse
import urllib.request
import urllib.error


VM_URL = os.getenv("VM_URL", "http://140.113.179.9:31888").rstrip("/")

AP_NAME = os.getenv("AP_NAME", "openwrt_ap")
AP_IFACE = os.getenv("AP_IFACE", "phy0-ap0")
AP_TARGET = os.getenv("OPENWRT", "192.168.100.112")

RATE_WINDOW = os.getenv("RATE_WINDOW", "5m")

QUERY_TIMEOUT = float(os.getenv("QUERY_TIMEOUT", "5"))


def prune_none(value):
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


def vm_query(query):
    """
    Query VictoriaMetrics /api/v1/query and return result vector.
    """
    url = VM_URL + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=QUERY_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"VictoriaMetrics query failed: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"VictoriaMetrics returned invalid JSON: {e}") from e

    if data.get("status") != "success":
        raise RuntimeError(f"VictoriaMetrics query error: {data}")

    return data.get("data", {}).get("result", [])


def value_of(item, default=None):
    try:
        return float(item["value"][1])
    except Exception:
        return default


def first_value(query, default=None):
    vec = vm_query(query)
    if not vec:
        return default
    return value_of(vec[0], default=default)


def percent_to_ratio(value):
    if value is None:
        return None
    return float(value) / 100.0


def bits_to_bytes_per_s(value):
    if value is None:
        return None
    return float(value) / 8.0


def vector_map_by_label(query, label):
    """
    Return:
      {
        label_value: metric_value
      }
    """
    out = {}
    for item in vm_query(query):
        metric = item.get("metric", {})
        key = metric.get(label)
        if key is None:
            continue
        out[key] = value_of(item, default=None)
    return out


def build_selector():
    return f'ap="{AP_NAME}",iface="{AP_IFACE}",target="{AP_TARGET}"'


def collect_wireless_access(selector):
    station_count = first_value(
        f'ap_wifi_station_count{{{selector}}}',
        default=0.0,
    )

    tx_bps = first_value(
        f'sum by(ap,iface,target) '
        f'(rate(ap_wifi_station_tx_bytes{{{selector}}}[{RATE_WINDOW}])) * 8',
        default=0.0,
    )

    rx_bps = first_value(
        f'sum by(ap,iface,target) '
        f'(rate(ap_wifi_station_rx_bytes{{{selector}}}[{RATE_WINDOW}])) * 8',
        default=0.0,
    )

    avg_tx_bitrate_mbps = first_value(
        f'avg by(ap,iface,target) '
        f'(ap_wifi_station_tx_bitrate_mbps{{{selector}}})',
        default=None,
    )

    avg_rx_bitrate_mbps = first_value(
        f'avg by(ap,iface,target) '
        f'(ap_wifi_station_rx_bitrate_mbps{{{selector}}})',
        default=None,
    )

    tx_failed_per_s = first_value(
        f'sum by(ap,iface,target) '
        f'(rate(ap_wifi_station_tx_failed{{{selector}}}[{RATE_WINDOW}]))',
        default=0.0,
    )

    avg_inactive_ms = first_value(
        f'avg by(ap,iface,target) '
        f'(ap_wifi_station_inactive_ms{{{selector}}})',
        default=None,
    )

    max_inactive_ms = first_value(
        f'max by(ap,iface,target) '
        f'(ap_wifi_station_inactive_ms{{{selector}}})',
        default=None,
    )

    avg_connected_seconds = first_value(
        f'avg by(ap,iface,target) '
        f'(ap_wifi_station_connected_seconds{{{selector}}})',
        default=None,
    )

    return {
        "station_count": int(station_count or 0),
        "tx_bits_per_s": tx_bps,
        "rx_bits_per_s": rx_bps,
        "avg_tx_bitrate_mbps": avg_tx_bitrate_mbps,
        "avg_rx_bitrate_mbps": avg_rx_bitrate_mbps,
        "tx_failed_per_s": tx_failed_per_s,
        "avg_inactive_ms": avg_inactive_ms,
        "max_inactive_ms": max_inactive_ms,
        "avg_connected_seconds": avg_connected_seconds,
    }


def collect_stations(selector):
    connected = vector_map_by_label(
        f'ap_wifi_station_connected_seconds{{{selector}}}',
        "station",
    )
    inactive = vector_map_by_label(
        f'ap_wifi_station_inactive_ms{{{selector}}}',
        "station",
    )
    tx_bitrate = vector_map_by_label(
        f'ap_wifi_station_tx_bitrate_mbps{{{selector}}}',
        "station",
    )
    rx_bitrate = vector_map_by_label(
        f'ap_wifi_station_rx_bitrate_mbps{{{selector}}}',
        "station",
    )
    tx_failed = vector_map_by_label(
        f'ap_wifi_station_tx_failed{{{selector}}}',
        "station",
    )
    tx_bps = vector_map_by_label(
        f'rate(ap_wifi_station_tx_bytes{{{selector}}}[{RATE_WINDOW}]) * 8',
        "station",
    )
    rx_bps = vector_map_by_label(
        f'rate(ap_wifi_station_rx_bytes{{{selector}}}[{RATE_WINDOW}]) * 8',
        "station",
    )

    station_ids = sorted(
        set(connected)
        | set(inactive)
        | set(tx_bitrate)
        | set(rx_bitrate)
        | set(tx_failed)
        | set(tx_bps)
        | set(rx_bps)
    )

    stations = []
    for station in station_ids:
        stations.append({
            "station": station,
            "inactive_ms": inactive.get(station),
            "connected_seconds": connected.get(station),
            "tx_bitrate_mbps": tx_bitrate.get(station),
            "rx_bitrate_mbps": rx_bitrate.get(station),
            "tx_bits_per_s": tx_bps.get(station),
            "rx_bits_per_s": rx_bps.get(station),
            "tx_failed_total": tx_failed.get(station),
        })

    return stations


def collect_device_resource():
    selector = f'ap="{AP_NAME}",target="{AP_TARGET}"'

    cpu_usage = first_value(
        f'ap_node_cpu_usage_percent{{{selector}}}',
        default=None,
    )

    cpu_idle = first_value(
        f'ap_node_cpu_idle_percent{{{selector}}}',
        default=None,
    )

    cpu_user = first_value(
        f'ap_node_cpu_user_percent{{{selector}}}',
        default=None,
    )

    cpu_system = first_value(
        f'ap_node_cpu_system_percent{{{selector}}}',
        default=None,
    )

    memory_usage = first_value(
        f'ap_node_memory_usage_percent{{{selector}}}',
        default=None,
    )

    mem_total = first_value(
        f'ap_node_memory_total_bytes{{{selector}}}',
        default=None,
    )

    mem_available = first_value(
        f'ap_node_memory_available_bytes{{{selector}}}',
        default=None,
    )

    mem_used = first_value(
        f'ap_node_memory_used_bytes{{{selector}}}',
        default=None,
    )

    mem_buffer = first_value(
        f'ap_node_memory_buffer_bytes{{{selector}}}',
        default=None,
    )

    mem_cached = first_value(
        f'ap_node_memory_cached_bytes{{{selector}}}',
        default=None,
    )

    load1 = first_value(
        f'ap_node_load1{{{selector}}}',
        default=None,
    )

    load5 = first_value(
        f'ap_node_load5{{{selector}}}',
        default=None,
    )

    load15 = first_value(
        f'ap_node_load15{{{selector}}}',
        default=None,
    )

    cpu_cores = first_value(
        f'ap_node_cpu_num_cores{{{selector}}}',
        default=None,
    )

    swap_total = first_value(
        f'ap_node_swap_total_bytes{{{selector}}}',
        default=None,
    )

    swap_available = first_value(
        f'ap_node_swap_available_bytes{{{selector}}}',
        default=None,
    )

    mem_free = None
    if mem_total is not None and mem_used is not None:
        mem_free = max(float(mem_total) - float(mem_used), 0.0)

    swap_used = None
    if swap_total is not None and swap_available is not None:
        swap_used = max(float(swap_total) - float(swap_available), 0.0)

    return {
        "source": "snmp_gateway+victoriametrics",
        "cpu_usage_percent": cpu_usage,
        "cpu_idle_percent": cpu_idle,
        "cpu_user_percent": cpu_user,
        "cpu_system_percent": cpu_system,
        "cpu_usage_ratio": percent_to_ratio(cpu_usage),
        "cpu_idle_ratio": percent_to_ratio(cpu_idle),
        "cpu_user_ratio": percent_to_ratio(cpu_user),
        "cpu_system_ratio": percent_to_ratio(cpu_system),
        "cpu_num_cores": cpu_cores,
        "memory_total_bytes": mem_total,
        "memory_available_bytes": mem_available,
        "memory_used_bytes": mem_used,
        "memory_free_bytes": mem_free,
        "memory_buffer_bytes": mem_buffer,
        "memory_cached_bytes": mem_cached,
        "memory_usage_percent": memory_usage,
        "memory_usage_ratio": percent_to_ratio(memory_usage),
        "swap_total_bytes": swap_total,
        "swap_used_bytes": swap_used,
        "swap_available_bytes": swap_available,
        "load1": load1,
        "load5": load5,
        "load15": load15,
    }


def collect_interface_traffic():
    selector = f'ap="{AP_NAME}",target="{AP_TARGET}",iface="{AP_IFACE}"'

    rx_bps = first_value(
        f'rate(ap_node_iface_rx_bytes_total{{{selector}}}[{RATE_WINDOW}]) * 8',
        default=None,
    )

    tx_bps = first_value(
        f'rate(ap_node_iface_tx_bytes_total{{{selector}}}[{RATE_WINDOW}]) * 8',
        default=None,
    )

    rx_errors_per_s = first_value(
        f'rate(ap_node_iface_rx_errors_total{{{selector}}}[{RATE_WINDOW}])',
        default=None,
    )

    tx_errors_per_s = first_value(
        f'rate(ap_node_iface_tx_errors_total{{{selector}}}[{RATE_WINDOW}])',
        default=None,
    )

    admin_status = first_value(
        f'ap_node_iface_admin_status{{{selector}}}',
        default=None,
    )

    oper_status = first_value(
        f'ap_node_iface_oper_status{{{selector}}}',
        default=None,
    )

    return {
        "source": "snmp_gateway+victoriametrics",
        "iface": AP_IFACE,
        "rx_bits_per_s": rx_bps,
        "tx_bits_per_s": tx_bps,
        "rx_errors_per_s": rx_errors_per_s,
        "tx_errors_per_s": tx_errors_per_s,
        "admin_status": admin_status,
        "oper_status": oper_status,
    }


def main():
    selector = build_selector()

    output = {
        "schema": "intentcontinuum.access_node.v1",
        "collector_status": "ok",
        "meta": {
            "timestamp": int(time.time()),
            "observer": socket.gethostname(),
            "target_node": AP_NAME,
            "target_ip": AP_TARGET,
            "iface": AP_IFACE,
            "role": "resource_limited_ap_gateway",
            "vm_url": VM_URL,
            "rate_window": RATE_WINDOW,
        },
        "access_node_semantic": {},
    }

    try:
        wireless = collect_wireless_access(selector)
        stations = collect_stations(selector)
        device_resource = collect_device_resource()
        interface_traffic = collect_interface_traffic()

        node_pressure = {
            "cpu_usage_percent": device_resource.get("cpu_usage_percent"),
            "memory_usage_percent": device_resource.get("memory_usage_percent"),
        }
        node_pressure_instant = {
            "source": "snmp_gateway+victoriametrics",
            "cpu_usage_percent": device_resource.get("cpu_usage_percent"),
            "cpu_user_percent": device_resource.get("cpu_user_percent"),
            "cpu_system_percent": device_resource.get("cpu_system_percent"),
            "cpu_idle_percent": device_resource.get("cpu_idle_percent"),
            "memory_usage_percent": device_resource.get("memory_usage_percent"),
            "mem_total_bytes": device_resource.get("memory_total_bytes"),
            "mem_used_bytes": device_resource.get("memory_used_bytes"),
            "mem_free_bytes": device_resource.get("memory_free_bytes"),
            "load_average": {
                "load1": device_resource.get("load1"),
                "load5": device_resource.get("load5"),
                "load15": device_resource.get("load15"),
            },
            "memory_capacity": {
                "source": "snmp_gateway+victoriametrics",
                "mem_available_bytes": device_resource.get("memory_available_bytes"),
                "swap_used_bytes": device_resource.get("swap_used_bytes"),
                "swap_total_bytes": device_resource.get("swap_total_bytes"),
                "swap_free_bytes": device_resource.get("swap_available_bytes"),
            },
            "network": {
                "rx_bits_per_s": interface_traffic.get("rx_bits_per_s"),
                "tx_bits_per_s": interface_traffic.get("tx_bits_per_s"),
                "rx_bytes_per_s": bits_to_bytes_per_s(interface_traffic.get("rx_bits_per_s")),
                "tx_bytes_per_s": bits_to_bytes_per_s(interface_traffic.get("tx_bits_per_s")),
            },
        }
        node_compute_features = {
            "source": "snmp_gateway+victoriametrics",
            "cpu_compute": {
                "source": "snmp_gateway+victoriametrics",
                "cpu_usage_percent": device_resource.get("cpu_usage_percent"),
                "cpu_user_percent": device_resource.get("cpu_user_percent"),
                "cpu_system_percent": device_resource.get("cpu_system_percent"),
                "cpu_idle_percent": device_resource.get("cpu_idle_percent"),
                "cpu_cores_total": device_resource.get("cpu_num_cores"),
                "load1": device_resource.get("load1"),
                "load5": device_resource.get("load5"),
                "load15": device_resource.get("load15"),
            },
            "ram_capacity": {
                "source": "snmp_gateway+victoriametrics",
                "mem_total_bytes": device_resource.get("memory_total_bytes"),
                "mem_used_bytes": device_resource.get("memory_used_bytes"),
                "mem_free_bytes": device_resource.get("memory_free_bytes"),
                "mem_available_bytes": device_resource.get("memory_available_bytes"),
                "swap_used_bytes": device_resource.get("swap_used_bytes"),
                "swap_total_bytes": device_resource.get("swap_total_bytes"),
                "swap_free_bytes": device_resource.get("swap_available_bytes"),
                "memory_usage_percent": device_resource.get("memory_usage_percent"),
            },
            "data_movement": {
                "source": "snmp_gateway+victoriametrics",
                "network_receive_bytes_per_s": bits_to_bytes_per_s(interface_traffic.get("rx_bits_per_s")),
                "network_transmit_bytes_per_s": bits_to_bytes_per_s(interface_traffic.get("tx_bits_per_s")),
                "network_receive_bits_per_s": interface_traffic.get("rx_bits_per_s"),
                "network_transmit_bits_per_s": interface_traffic.get("tx_bits_per_s"),
            },
        }

        output["access_node_semantic"] = {
            "source": "ap_gateway+snmp_gateway+victoriametrics",
            "wireless_access": wireless,
            "stations": stations,
            "device_resource": device_resource,
            "interface_traffic": interface_traffic,
            "node_pressure": node_pressure,
            "node_pressure_instant": node_pressure_instant,
            "node_compute_features": node_compute_features,
        }

    except Exception as e:
        output["collector_status"] = "error"
        output["error"] = str(e)

    print(json.dumps(prune_none(output), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
