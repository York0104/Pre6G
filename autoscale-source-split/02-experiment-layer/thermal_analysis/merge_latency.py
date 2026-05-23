#!/usr/bin/env python3
import argparse
import csv
from bisect import bisect_left
from datetime import datetime, timedelta
from pathlib import Path


def parse_ts(s: str):
    return datetime.fromisoformat(s.strip())


def load_csv(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_key = "timestamp" if "timestamp" in row else "client_ts"
            row["_ts"] = parse_ts(row[ts_key])
            rows.append(row)
    return rows


def build_index(rows):
    rows = sorted(rows, key=lambda r: r["_ts"])
    times = [r["_ts"] for r in rows]
    return rows, times


def nearest_row(ts, rows, times, tolerance_sec=2.0):
    idx = bisect_left(times, ts)
    cand = []
    if idx < len(rows):
        cand.append(rows[idx])
    if idx > 0:
        cand.append(rows[idx - 1])

    best = None
    best_diff = None
    tol = timedelta(seconds=tolerance_sec)
    for c in cand:
        diff = abs(c["_ts"] - ts)
        if diff <= tol and (best_diff is None or diff < best_diff):
            best = c
            best_diff = diff
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--tolerance-sec", type=float, default=2.0)
    args = ap.parse_args()

    run_dir = Path(args.run_dir).expanduser()
    aligned_path = run_dir / "aligned_metrics.csv"
    latency_path = run_dir / "latency.csv"
    out_path = run_dir / "aligned_service_metrics.csv"

    aligned_rows = load_csv(aligned_path)
    latency_rows = load_csv(latency_path)

    aligned_rows_sorted, aligned_times = build_index(aligned_rows)

    merged = []
    for lr in latency_rows:
        ar = nearest_row(lr["_ts"], aligned_rows_sorted, aligned_times, args.tolerance_sec)

        row = {
            "client_ts": lr["client_ts"],
            "req_id": lr["req_id"],
            "latency_ms_client": lr["latency_ms_client"],
            "status_code": lr["status_code"],
            "success": lr["success"],
            "server_time": lr["server_time"],
            "server_latency_ms": lr["server_latency_ms"],
            "num_boxes": lr["num_boxes"],
            "error_msg": lr["error_msg"],
        }

        if ar is not None:
            for k, v in ar.items():
                if not k.startswith("_"):
                    row[f"aligned_{k}"] = v
        merged.append(row)

    fieldnames = list(merged[0].keys()) if merged else []
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)

    print(f"written: {out_path}")


if __name__ == "__main__":
    main()
