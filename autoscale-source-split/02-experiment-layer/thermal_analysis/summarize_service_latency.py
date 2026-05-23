#!/usr/bin/env python3
import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


def to_float(v):
    try:
        return float(v)
    except Exception:
        return None


def percentile(values, p):
    if not values:
        return None
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return vals[int(k)]
    return vals[f] + (vals[c] - vals[f]) * (k - f)


def mean(values):
    return sum(values) / len(values) if values else None


def fmt(v):
    return "" if v is None else round(v, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()

    path = Path(args.csv).expanduser()
    rows = list(csv.DictReader(path.open("r", encoding="utf-8")))

    groups = defaultdict(list)
    for r in rows:
        phase = r.get("aligned_phase", "")
        if not phase:
            continue
        groups[phase].append(r)

    print("phase,count,client_mean,client_p50,client_p95,server_mean,server_p50,server_p95,temp_mean,power_mean")
    for phase in ["warmup", "normal_hold", "fault_ramp_up", "fault_hold"]:
        g = groups.get(phase, [])
        if not g:
            continue

        client = [to_float(r["latency_ms_client"]) for r in g if to_float(r["latency_ms_client"]) is not None]
        server = [to_float(r["server_latency_ms"]) for r in g if to_float(r["server_latency_ms"]) is not None]
        temp = [to_float(r["aligned_gpu_temp_c"]) for r in g if to_float(r["aligned_gpu_temp_c"]) is not None]
        power = [to_float(r["aligned_gpu_power_w"]) for r in g if to_float(r["aligned_gpu_power_w"]) is not None]

        print(",".join(map(str, [
            phase,
            len(g),
            fmt(mean(client)),
            fmt(percentile(client, 0.50)),
            fmt(percentile(client, 0.95)),
            fmt(mean(server)),
            fmt(percentile(server, 0.50)),
            fmt(percentile(server, 0.95)),
            fmt(mean(temp)),
            fmt(mean(power)),
        ])))


if __name__ == "__main__":
    main()
