#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_QUERIES = {
    "dcgm_gpu_util": "max(timestamp(DCGM_FI_DEV_GPU_UTIL))",
    "dcgm_fb_used": "max(timestamp(DCGM_FI_DEV_FB_USED))",
    "cadvisor_cpu": 'max(timestamp(container_cpu_usage_seconds_total{container!=""}))',
    "kube_pod_info": "max(timestamp(kube_pod_info))",
    "node_cpu": 'max(timestamp(node_cpu_seconds_total{mode!="idle"}))',
}


def vm_query(vm_url: str, query: str, timeout_s: float) -> dict:
    url = vm_url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("status") != "success":
        raise RuntimeError(f"VictoriaMetrics query failed: {data}")
    return data


def first_scalar(data: dict) -> float | None:
    result = data.get("data", {}).get("result", [])
    if not result:
        return None
    value = result[0].get("value")
    if not value or len(value) < 2:
        return None
    try:
        return float(value[1])
    except Exception:
        return None


def quantile(values: list[float], p: float) -> float:
    if not values:
        return math.nan
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    frac = pos - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    by_name = {}
    for row in rows:
        by_name.setdefault(row["query_name"], []).append(row)
    for name, group in sorted(by_name.items()):
        ok = [r for r in group if r["ok"] == "1" and r.get("sample_age_s") not in ("", None)]
        ages = [float(r["sample_age_s"]) for r in ok]
        sample_ts = [float(r["sample_ts"]) for r in ok if r.get("sample_ts") not in ("", None)]
        deltas = []
        last = None
        for ts in sample_ts:
            if last is not None and ts != last:
                deltas.append(ts - last)
            last = ts
        out.append(
            {
                "query_name": name,
                "rows": len(group),
                "ok_rows": len(ok),
                "sample_age_p50_s": quantile(ages, 0.5),
                "sample_age_p95_s": quantile(ages, 0.95),
                "sample_age_max_s": max(ages) if ages else math.nan,
                "sample_update_delta_p50_s": quantile(deltas, 0.5),
                "sample_update_delta_p95_s": quantile(deltas, 0.95),
                "distinct_sample_timestamps": len(set(sample_ts)),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vm-url", default="http://140.113.179.9:31888")
    ap.add_argument("--seconds", type=int, default=45)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--out-dir", type=Path, default=Path("/tmp/pre6g_vm_latency_probe"))
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    start = time.time()
    while True:
        probe_ts = time.time()
        for name, query in DEFAULT_QUERIES.items():
            row = {
                "probe_ts": f"{probe_ts:.6f}",
                "query_name": name,
                "query": query,
                "ok": "0",
                "sample_ts": "",
                "sample_age_s": "",
                "error": "",
            }
            try:
                sample_ts = first_scalar(vm_query(args.vm_url, query, args.timeout))
                row["ok"] = "1" if sample_ts is not None else "0"
                if sample_ts is not None:
                    row["sample_ts"] = f"{sample_ts:.6f}"
                    row["sample_age_s"] = f"{probe_ts - sample_ts:.6f}"
                else:
                    row["error"] = "empty result"
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
        if time.time() - start >= args.seconds:
            break
        time.sleep(max(0.0, args.interval - (time.time() - probe_ts)))

    raw_path = args.out_dir / "vm_latency_offset_probe_raw.csv"
    summary_path = args.out_dir / "vm_latency_offset_probe_summary.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)
    print(f"[OK] raw={raw_path}")
    print(f"[OK] summary={summary_path}")
    for row in summary:
        print(
            "{query_name}: ok={ok_rows}/{rows}, age_p50={sample_age_p50_s:.3f}s, "
            "age_p95={sample_age_p95_s:.3f}s, update_p50={sample_update_delta_p50_s:.3f}s".format(**row)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
