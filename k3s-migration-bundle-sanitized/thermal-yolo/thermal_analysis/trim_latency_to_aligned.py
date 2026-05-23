#!/usr/bin/env python3
import argparse
import csv
from datetime import datetime
from pathlib import Path


def parse_ts(s: str):
    return datetime.fromisoformat(s.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()

    run_dir = Path(args.run_dir).expanduser()
    aligned_path = run_dir / "aligned_metrics.csv"
    latency_path = run_dir / "latency.csv"
    out_path = run_dir / "latency_trimmed.csv"

    with aligned_path.open("r", encoding="utf-8") as f:
        aligned_rows = list(csv.DictReader(f))
    if not aligned_rows:
        raise RuntimeError("aligned_metrics.csv is empty")

    aligned_end_ts = max(parse_ts(r["timestamp"]) for r in aligned_rows)

    with latency_path.open("r", encoding="utf-8") as f:
        latency_rows = list(csv.DictReader(f))
    if not latency_rows:
        raise RuntimeError("latency.csv is empty")

    kept = []
    for r in latency_rows:
        ts = parse_ts(r["client_ts"])
        if ts <= aligned_end_ts:
            kept.append(r)

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=latency_rows[0].keys())
        writer.writeheader()
        writer.writerows(kept)

    print(f"aligned_end_ts={aligned_end_ts.isoformat()}")
    print(f"latency_rows_in={len(latency_rows)}")
    print(f"latency_rows_kept={len(kept)}")
    print(f"written: {out_path}")


if __name__ == "__main__":
    main()
