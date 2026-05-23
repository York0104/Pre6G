import csv
import glob
import json
import os
from bisect import bisect_left
from datetime import datetime, timedelta
from pathlib import Path
import argparse


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.strip())


def safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def flatten_dict(d, parent_key="", sep="__"):
    items = {}
    if not isinstance(d, dict):
        return items

    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)

        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep=sep))
        elif isinstance(v, list):
            # Preserve list-shaped payloads without breaking CSV output.
            items[new_key] = json.dumps(v, ensure_ascii=False)
        else:
            items[new_key] = v

    return items


EXPECTED_NULL_COLUMNS = [
    "metrics__target_node_semantic__gpu_bound_features__data_movement__pcie_tx_throughput_avg",
    "metrics__target_node_semantic__gpu_bound_features__data_movement__pcie_rx_throughput_avg",
    "metrics__target_node_semantic__node_compute_features__cpu_compute__perf_cpu_cycles",
    "metrics__target_node_semantic__node_compute_features__cpu_compute__perf_instructions",
    "metrics__target_node_semantic__node_compute_features__cpu_compute__perf_instructions_per_cycle",
    "metrics__target_node_semantic__node_compute_features__cpu_compute__perf_stalled_cycles",
]


def load_thermal_csv(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["_ts"] = parse_ts(row["timestamp"])
            rows.append(row)
    return rows


def load_stress_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)

            row = {
                "sample_time": obj.get("sample_time"),
                "_ts": parse_ts(obj.get("sample_time")),
                "observer_node": obj.get("observer_node"),
                "namespace": obj.get("namespace"),
                "stress_phase": safe_get(obj, "stress_phase", "phase_name"),
                "stress_load_percent": safe_get(obj, "stress_phase", "load_percent"),
            }
            metrics = obj.get("metrics", {}) or {}
            flat_metrics = flatten_dict(metrics, parent_key="metrics")
            row.update(flat_metrics)
            rows.append(row)
    return rows


def build_time_index(rows):
    rows_sorted = sorted(rows, key=lambda r: r["_ts"])
    times = [r["_ts"] for r in rows_sorted]
    return rows_sorted, times


def nearest_row(ts, rows_sorted, times, tolerance_sec=2.0):
    if not rows_sorted:
        return None

    idx = bisect_left(times, ts)
    candidates = []
    if idx < len(rows_sorted):
        candidates.append(rows_sorted[idx])
    if idx > 0:
        candidates.append(rows_sorted[idx - 1])

    best = None
    best_diff = None
    tol = timedelta(seconds=tolerance_sec)

    for c in candidates:
        diff = abs(c["_ts"] - ts)
        if diff <= tol and (best_diff is None or diff < best_diff):
            best = c
            best_diff = diff

    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, help="e.g. ~/exp_runs/t80_r1_20260411_122057")
    ap.add_argument("--tolerance-sec", type=float, default=2.0)
    args = ap.parse_args()

    run_dir = Path(os.path.expanduser(args.run_dir))
    worker_dir = run_dir / "worker_logs"

    thermal_path = worker_dir / "thermal.csv"
    stress_candidates = sorted(run_dir.glob("stress_metrics_*.jsonl"))

    if not thermal_path.exists():
        raise FileNotFoundError(f"thermal.csv not found: {thermal_path}")
    if not stress_candidates:
        raise FileNotFoundError(f"stress_metrics_*.jsonl not found under: {run_dir}")

    stress_path = stress_candidates[0]

    thermal_rows = load_thermal_csv(thermal_path)
    stress_rows = load_stress_jsonl(stress_path)

    stress_sorted, stress_times = build_time_index(stress_rows)

    merged_rows = []
    for tr in thermal_rows:
        sr = nearest_row(tr["_ts"], stress_sorted, stress_times, tolerance_sec=args.tolerance_sec)

        merged = {
            "timestamp": tr["timestamp"],
            "elapsed_s": tr.get("elapsed_s"),
            "phase": tr.get("phase"),
            "binary_label": tr.get("binary_label"),
            "phase_elapsed_s": tr.get("phase_elapsed_s"),
            "target_temp_c": tr.get("target_temp_c"),
            "band_c": tr.get("band_c"),
            "stable_counter_s": tr.get("stable_counter_s"),
            "gpu_temp_c": tr.get("gpu_temp_c"),
            "gpu_state": tr.get("gpu_state"),
            "gpu_util_pct": tr.get("gpu_util_pct"),
            "gpu_power_w": tr.get("gpu_power_w"),
            "gpu_fan_pct": tr.get("gpu_fan_pct"),
            "gpu_clock_mhz": tr.get("gpu_clock_mhz"),
            "gpu_mem_clock_mhz": tr.get("gpu_mem_clock_mhz"),
            "current_mode": tr.get("current_mode"),
            "desired_mode": tr.get("desired_mode"),
            "reason": tr.get("reason"),
            "infeasible": tr.get("infeasible"),
        }

        if sr is not None:
            merged["matched_sample_time"] = sr.get("sample_time")
            for k, v in sr.items():
                if k not in ("_ts", "sample_time"):
                    merged[k] = v
        else:
            merged["matched_sample_time"] = ""

        for col in EXPECTED_NULL_COLUMNS:
            merged.setdefault(col, "")

        merged_rows.append(merged)

    out_csv = run_dir / "aligned_metrics.csv"
    out_json = run_dir / "aligned_summary.json"

    fieldnames = []
    if merged_rows:
        seen = set()
        for row in merged_rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_rows)

    valid = [r for r in merged_rows if r["matched_sample_time"]]
    in_band = [r for r in valid if r["gpu_state"] == "within_band"]

    def avg(rows, key):
        vals = []
        for r in rows:
            v = r.get(key, "")
            try:
                vals.append(float(v))
            except Exception:
                pass
        return round(sum(vals) / len(vals), 4) if vals else None

    summary = {
        "run_dir": str(run_dir),
        "thermal_rows": len(thermal_rows),
        "stress_rows": len(stress_rows),
        "aligned_rows": len(merged_rows),
        "matched_rows": len(valid),
        "within_band_rows": len(in_band),
        "within_band_ratio": round(len(in_band) / len(valid), 4) if valid else None,

        "avg_gpu_temp_all": avg(valid, "gpu_temp_c"),
        "avg_gpu_temp_within_band": avg(in_band, "gpu_temp_c"),
        "avg_gpu_power_all": avg(valid, "gpu_power_w"),
        "avg_gpu_util_all": avg(valid, "gpu_util_pct"),

        "avg_node_cpu_percent_instant_all": avg(valid, "node_cpu_usage_percent_instant"),
        "avg_node_mem_percent_instant_all": avg(valid, "node_memory_usage_percent_instant"),

        "avg_node_cpu_percent_instant_within_band": avg(in_band, "node_cpu_usage_percent_instant"),
        "avg_node_mem_percent_instant_within_band": avg(in_band, "node_memory_usage_percent_instant"),
    }

    with out_json.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"written: {out_csv}")
    print(f"written: {out_json}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
