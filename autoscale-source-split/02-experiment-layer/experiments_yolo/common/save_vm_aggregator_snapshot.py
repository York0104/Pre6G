#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def flatten(obj: Any, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    if out is None:
        out = {}

    if isinstance(obj, dict):
        for key, value in obj.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            flatten(value, next_prefix, out)
    elif isinstance(obj, list):
        out[prefix] = json.dumps(obj, ensure_ascii=False)
    else:
        out[prefix] = obj

    return out


def write_summary(out_path: Path, data: dict[str, Any]) -> None:
    flat = flatten(data)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("== vm_aggregator snapshot ==\n")
        f.write(f"collector_status: {data.get('collector_status')}\n")
        collector_error = data.get("collector_error")
        if collector_error:
            f.write(f"collector_error: {collector_error}\n")
        f.write("\n")
        for key in sorted(flat):
            value = flat[key]
            if isinstance(value, str):
                f.write(f"{key}: {value}\n")
            else:
                f.write(f"{key}: {json.dumps(value, ensure_ascii=False)}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aggregator", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--node", required=True)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--k8s-node", default="")
    ap.add_argument("--mode", default="fast")
    args = ap.parse_args()

    aggregator = Path(args.aggregator).resolve()
    run_dir = Path(args.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["NODE"] = args.node
    env["NAMESPACE"] = args.namespace
    env["MODE"] = args.mode
    env["DEBUG_OUTPUT"] = env.get("DEBUG_OUTPUT", "1")
    if args.k8s_node:
        env["K8S_NODE"] = args.k8s_node

    proc = subprocess.run(
        [sys.executable, str(aggregator)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=30,
    )

    raw_path = run_dir / "vm_aggregator_snapshot.raw.txt"
    raw_path.write_text(proc.stdout, encoding="utf-8")

    stderr_path = run_dir / "vm_aggregator_snapshot.stderr.txt"
    stderr_path.write_text(proc.stderr, encoding="utf-8")

    if proc.returncode != 0:
        raise SystemExit(f"vm_aggregator failed with returncode={proc.returncode}")

    data = json.loads(proc.stdout)
    (run_dir / "vm_aggregator_snapshot.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_summary(run_dir / "vm_aggregator_snapshot.txt", data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
