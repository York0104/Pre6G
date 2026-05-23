#!/usr/bin/env python3
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def now_iso():
    return datetime.now().isoformat(timespec="milliseconds")


def flatten(obj, prefix="", out=None):
    if out is None:
        out = {}

    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            flatten(v, key, out)
    elif isinstance(obj, list):
        out[prefix] = json.dumps(obj, ensure_ascii=False)
    else:
        out[prefix] = obj

    return out


def run_aggregator(aggregator_path, env):
    try:
        p = subprocess.run(
            [sys.executable, str(aggregator_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=25,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout=25s"

    if p.returncode != 0:
        stderr = p.stderr.strip()
        if len(stderr) > 4000:
            stderr = f"{stderr[:2000]}\n...<truncated>...\n{stderr[-2000:]}"
        return None, f"returncode={p.returncode}; stderr={stderr}"

    text = p.stdout.strip()

    try:
        return json.loads(text), None
    except Exception as e:
        return None, f"json_parse_error={e}; stdout_head={text[:500]}"


def write_rows(out_path, rows, all_fields):
    fixed_fields = [
        "ts",
        "collector_elapsed_s",
        "collector_ok",
        "collector_error",
        "monitor_node",
        "monitor_namespace",
    ]
    fields = fixed_fields + sorted(k for k in all_fields if k not in fixed_fields)

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aggregator", required=True, help="path to vm_aggregator.py")
    ap.add_argument("--out", required=True, help="output csv path")
    ap.add_argument("--seconds", type=int, required=True)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--node", default="")
    ap.add_argument("--namespace", default="intent-lab")
    ap.add_argument("--vm-url", default="")
    ap.add_argument("--netdata-url", default="")
    ap.add_argument("--netdata-child-url", default="")
    ap.add_argument("--netdata-parent-base-url", default="")
    ap.add_argument("--node-exporter-instance", default="")
    ap.add_argument("--mode", default="fast")
    args = ap.parse_args()

    aggregator_path = Path(args.aggregator).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["NODE"] = args.node
    env["NAMESPACE"] = args.namespace
    env["MODE"] = args.mode
    env["DEBUG_OUTPUT"] = "1"
    if args.vm_url:
        env["VM_URL"] = args.vm_url
    if args.netdata_url:
        env["NETDATA_URL"] = args.netdata_url
    if args.netdata_child_url:
        env["NETDATA_CHILD_URL"] = args.netdata_child_url
    if args.netdata_parent_base_url:
        env["NETDATA_PARENT_BASE_URL"] = args.netdata_parent_base_url
    if args.node_exporter_instance:
        env["NODE_EXPORTER_INSTANCE"] = args.node_exporter_instance

    start = time.time()
    rows = []
    all_fields = set()

    print("[INFO] collect vm aggregator")
    print(f"[INFO] aggregator={aggregator_path}")
    print(f"[INFO] out={out_path}")
    print(f"[INFO] seconds={args.seconds}, interval={args.interval}")
    print(
        f"[INFO] NODE={env.get('NODE')}, "
        f"NAMESPACE={env.get('NAMESPACE')}, VM_URL={env.get('VM_URL', '')}"
    )

    while True:
        t0 = time.time()
        ts = now_iso()

        data, err = run_aggregator(aggregator_path, env)

        row = {
            "ts": ts,
            "collector_elapsed_s": round(t0 - start, 3),
            "collector_ok": 1 if err is None else 0,
            "collector_error": "" if err is None else err,
            "monitor_node": args.node,
            "monitor_namespace": args.namespace,
        }

        if data is not None:
            flat = flatten(data)
            for k, v in flat.items():
                row[f"vmagg.{k}"] = v

        rows.append(row)
        all_fields.update(row.keys())
        write_rows(out_path, rows, all_fields)

        if time.time() - start >= args.seconds:
            break

        sleep_s = max(0.0, args.interval - (time.time() - t0))
        time.sleep(sleep_s)

    print(f"[OK] wrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
