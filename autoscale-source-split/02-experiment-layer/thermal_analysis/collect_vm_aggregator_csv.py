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


def pop_vm_query_samples(data):
    if not isinstance(data, dict):
        return []
    debug = data.get("_debug")
    if not isinstance(debug, dict):
        return []
    samples = debug.pop("vm_query_samples", [])
    return samples if isinstance(samples, list) else []


def append_vm_query_samples(out_path, collector_row, samples):
    if not samples:
        return
    item = {
        "ts": collector_row["ts"],
        "collector_elapsed_s": collector_row["collector_elapsed_s"],
        "collector_ok": collector_row["collector_ok"],
        "monitor_node": collector_row["monitor_node"],
        "monitor_namespace": collector_row["monitor_namespace"],
        "samples": samples,
    }
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        f.write("\n")


def write_rows(out_path, rows, all_fields):
    fixed_fields = [
        "ts",
        "collector_elapsed_s",
        "collector_ok",
        "collector_error",
        "collector_extra_fields_dropped",
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
    ap.add_argument(
        "--vm-query-samples-out",
        default="",
        help="optional JSONL sidecar for per-query VM sample timestamps/ages",
    )
    args = ap.parse_args()

    aggregator_path = Path(args.aggregator).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    samples_out_path = (
        Path(args.vm_query_samples_out).expanduser().resolve()
        if args.vm_query_samples_out
        else out_path.with_name(f"{out_path.stem}.vm_query_samples.jsonl")
    )
    samples_out_path.parent.mkdir(parents=True, exist_ok=True)
    samples_out_path.write_text("", encoding="utf-8")

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
    csv_fp = None
    writer = None
    fields = None
    row_count = 0

    print("[INFO] collect vm aggregator")
    print(f"[INFO] aggregator={aggregator_path}")
    print(f"[INFO] out={out_path}")
    print(f"[INFO] vm_query_samples_out={samples_out_path}")
    print(f"[INFO] seconds={args.seconds}, interval={args.interval}")
    print(
        f"[INFO] NODE={env.get('NODE')}, "
        f"NAMESPACE={env.get('NAMESPACE')}, VM_URL={env.get('VM_URL', '')}"
    )

    try:
        while True:
            t0 = time.time()
            ts = now_iso()

            data, err = run_aggregator(aggregator_path, env)

            row = {
                "ts": ts,
                "collector_elapsed_s": round(t0 - start, 3),
                "collector_ok": 1 if err is None else 0,
                "collector_error": "" if err is None else err,
                "collector_extra_fields_dropped": 0,
                "monitor_node": args.node,
                "monitor_namespace": args.namespace,
            }

            if data is not None:
                vm_query_samples = pop_vm_query_samples(data)
                append_vm_query_samples(samples_out_path, row, vm_query_samples)
                row["vmagg._debug.vm_query_samples_count"] = len(vm_query_samples)
                row["vmagg._debug.vm_query_samples_sidecar"] = str(samples_out_path)
                flat = flatten(data)
                for k, v in flat.items():
                    row[f"vmagg.{k}"] = v

            if writer is None:
                fixed_fields = [
                    "ts",
                    "collector_elapsed_s",
                    "collector_ok",
                    "collector_error",
                    "collector_extra_fields_dropped",
                    "monitor_node",
                    "monitor_namespace",
                ]
                fields = fixed_fields + sorted(k for k in row.keys() if k not in fixed_fields)
                csv_fp = out_path.open("w", newline="", encoding="utf-8")
                writer = csv.DictWriter(csv_fp, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()

            extras = set(row.keys()) - set(fields)
            row["collector_extra_fields_dropped"] = len(extras)
            writer.writerow(row)
            csv_fp.flush()
            row_count += 1

            if time.time() - start >= args.seconds:
                break

            sleep_s = max(0.0, args.interval - (time.time() - t0))
            time.sleep(sleep_s)
    finally:
        if csv_fp is not None:
            csv_fp.close()

    print(f"[OK] wrote {row_count} rows to {out_path}")


if __name__ == "__main__":
    main()
