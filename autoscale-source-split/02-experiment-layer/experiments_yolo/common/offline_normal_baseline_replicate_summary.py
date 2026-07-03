#!/usr/bin/env python3
"""Summarize replicated normal-cooling open-loop baseline by offered RPS."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def percentile(values: List[float], q: float) -> float | None:
    vals = sorted(v for v in values if math.isfinite(v))
    if not vals:
        return None
    idx = (len(vals) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(vals) - 1)
    frac = idx - lo
    return vals[lo] + (vals[hi] - vals[lo]) * frac


def summarize_group(rows: List[Dict[str, str]], rps: float) -> Dict[str, Any]:
    metrics = [
        "scheduled_request_count",
        "completed_request_count",
        "drop_ratio",
        "timeout_rate",
        "error_rate",
        "latency_p50_median",
        "latency_p95_median",
        "latency_p99_median",
        "gpu_temp_c_median",
        "gpu_temp_c_p95",
        "sm_clock_mhz_median",
        "power_w_median",
        "gpu_util_pct_p95",
        "vm_sample_age_max_s",
    ]
    out: Dict[str, Any] = {"offered_rps": rps, "replicates": len(rows)}
    for metric in metrics:
        vals = [num(row.get(metric)) for row in rows]
        vals = [v for v in vals if v is not None]
        out[f"{metric}_median"] = percentile(vals, 0.5)
        out[f"{metric}_iqr"] = (percentile(vals, 0.75) - percentile(vals, 0.25)) if len(vals) >= 2 else 0.0
        out[f"{metric}_min"] = min(vals) if vals else None
        out[f"{metric}_max"] = max(vals) if vals else None
    out["all_completed"] = all(str(row.get("completed")).lower() == "true" for row in rows)
    out["any_abort_reason"] = ";".join(sorted({row.get("abort_reason", "") for row in rows if row.get("abort_reason", "")}))
    return out


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: List[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def run(args: argparse.Namespace) -> int:
    input_root = Path(args.input_root)
    out_dir = Path(args.out_dir)
    summary_path = input_root / "calibration_analysis" / "normal_load_calibration_summary.csv"
    rows = read_csv(summary_path)
    groups: Dict[float, List[Dict[str, str]]] = {}
    for row in rows:
        rps = num(row.get("offered_rps_median"))
        if rps is None:
            continue
        groups.setdefault(rps, []).append(row)
    out_rows = [summarize_group(rows, rps) for rps, rows in sorted(groups.items())]
    write_csv(out_dir / "normal_baseline_by_offered_rps.csv", out_rows)
    manifest = {"input_root": str(input_root), "groups": len(out_rows), "runs": len(rows)}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = [
        "# Replicated normal-cooling baseline summary",
        "",
        f"- input_root: `{input_root}`",
        f"- runs: `{len(rows)}`",
        f"- offered RPS groups: `{len(out_rows)}`",
        "",
        "| offered_rps | reps | completed | latency_p95_median | latency_p95_iqr | gpu_temp_p95_median | sm_clock_median | vm_age_max_median |",
        "|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in out_rows:
        report.append(
            "| "
            f"{row['offered_rps']} | {row['replicates']} | {row['all_completed']} | "
            f"{row.get('latency_p95_median_median')} | {row.get('latency_p95_median_iqr')} | "
            f"{row.get('gpu_temp_c_p95_median')} | {row.get('sm_clock_mhz_median_median')} | "
            f"{row.get('vm_sample_age_max_s_median')} |"
        )
    report.extend(
        [
            "",
            "此 replicated normal baseline 可用於下一步 normal-load residual false-alarm validation；尚未包含 cooling-constrained condition。",
        ]
    )
    (out_dir / "normal_baseline_replicate_report_zh.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root", required=True)
    p.add_argument("--out-dir", required=True)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
