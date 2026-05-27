#!/usr/bin/env python3
import os
import re
import time
import hashlib
import subprocess
import urllib.request
import urllib.error

OPENWRT = os.getenv("OPENWRT", "192.168.1.1")
AP_IFACE = os.getenv("AP_IFACE", "phy0-ap0")
AP_NAME = os.getenv("AP_NAME", "openwrt_ap")
SSH_KEY = os.getenv("SSH_KEY", os.path.expanduser("~/.ssh/openwrt_ap_ed25519"))
INTERVAL = int(os.getenv("INTERVAL", "10"))

# VictoriaMetrics import endpoint.
# 請依你的 VM service 或 port-forward 修改。
VM_URL = os.getenv("VM_URL", "http://140.113.179.9:31888/api/v1/import/prometheus")

# 不建議直接把 client MAC 存進長期資料庫，這裡用 hash 匿名化。
MAC_SALT = os.getenv("MAC_SALT", "pre6g_ap_gateway")


def run_ssh(command: str) -> str:
    cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=3",
        f"root@{OPENWRT}",
        command,
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=8,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())

    return result.stdout


def station_hash(mac: str) -> str:
    raw = f"{MAC_SALT}:{mac.lower()}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def parse_float_from_line(line: str):
    m = re.search(r"(-?\d+(?:\.\d+)?)", line)
    return float(m.group(1)) if m else None


def parse_int_from_line(line: str):
    m = re.search(r"(-?\d+)", line)
    return int(m.group(1)) if m else None


def parse_station_dump(text: str):
    stations = []
    cur = None

    for line in text.splitlines():
        m = re.match(r"Station\s+([0-9a-fA-F:]{17})", line)
        if m:
            if cur:
                stations.append(cur)
            mac = m.group(1).lower()
            cur = {
                "mac": mac,
                "station": station_hash(mac),
            }
            continue

        if cur is None:
            continue

        s = line.strip()

        if s.startswith("inactive time:"):
            cur["inactive_ms"] = parse_int_from_line(s)

        elif s.startswith("rx bytes:"):
            cur["rx_bytes"] = parse_int_from_line(s)

        elif s.startswith("tx bytes:"):
            cur["tx_bytes"] = parse_int_from_line(s)

        elif s.startswith("rx packets:"):
            cur["rx_packets"] = parse_int_from_line(s)

        elif s.startswith("tx packets:"):
            cur["tx_packets"] = parse_int_from_line(s)

        elif s.startswith("tx retries:"):
            cur["tx_retries"] = parse_int_from_line(s)

        elif s.startswith("tx failed:"):
            cur["tx_failed"] = parse_int_from_line(s)

        elif s.startswith("signal avg:"):
            cur["signal_avg_dbm"] = parse_float_from_line(s)

        elif s.startswith("signal:"):
            cur["signal_dbm"] = parse_float_from_line(s)

        elif s.startswith("tx bitrate:"):
            cur["tx_bitrate_mbps"] = parse_float_from_line(s)

        elif s.startswith("rx bitrate:"):
            cur["rx_bitrate_mbps"] = parse_float_from_line(s)

        elif s.startswith("connected time:"):
            cur["connected_seconds"] = parse_int_from_line(s)

    if cur:
        stations.append(cur)

    return stations


def metric_line(name: str, value, labels: dict):
    if value is None:
        return None

    label_str = ",".join([f'{k}="{v}"' for k, v in labels.items()])
    return f"{name}{{{label_str}}} {value}"


def build_metrics(stations):
    lines = []
    base_labels = {
        "ap": AP_NAME,
        "target": OPENWRT,
        "iface": AP_IFACE,
    }

    lines.append(metric_line(
        "ap_wifi_station_count",
        len(stations),
        base_labels,
    ))

    for st in stations:
        labels = {
            **base_labels,
            "station": st["station"],
        }

        fields = {
            "ap_wifi_station_inactive_ms": "inactive_ms",
            "ap_wifi_station_rx_bytes": "rx_bytes",
            "ap_wifi_station_tx_bytes": "tx_bytes",
            "ap_wifi_station_rx_packets": "rx_packets",
            "ap_wifi_station_tx_packets": "tx_packets",
            "ap_wifi_station_tx_retries": "tx_retries",
            "ap_wifi_station_tx_failed": "tx_failed",
            "ap_wifi_station_signal_dbm": "signal_dbm",
            "ap_wifi_station_signal_avg_dbm": "signal_avg_dbm",
            "ap_wifi_station_tx_bitrate_mbps": "tx_bitrate_mbps",
            "ap_wifi_station_rx_bitrate_mbps": "rx_bitrate_mbps",
            "ap_wifi_station_connected_seconds": "connected_seconds",
        }

        for metric_name, key in fields.items():
            line = metric_line(metric_name, st.get(key), labels)
            if line:
                lines.append(line)

    return "\n".join(lines) + "\n"


def push_to_vm(payload: str):
    data = payload.encode()
    req = urllib.request.Request(
        VM_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "text/plain"},
    )

    with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"VictoriaMetrics HTTP status {resp.status}")


def main():
    while True:
        try:
            raw = run_ssh(f"iw dev {AP_IFACE} station dump")
            stations = parse_station_dump(raw)
            payload = build_metrics(stations)

            print(payload.strip(), flush=True)

            if VM_URL:
                push_to_vm(payload)

        except Exception as e:
            print(f"[ap_gateway] error: {e}", flush=True)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
