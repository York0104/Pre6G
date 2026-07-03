#!/usr/bin/env python3
"""Summarize normal-cooling open-loop calibration candidate runs."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def f(row: Dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        raw = str(row.get(key, "") or "").strip()
        if not raw:
            return default
        match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
        return float(match.group(0)) if match else default
    except ValueError:
        return default


def get_cell(row: Dict[str, str], choices: List[str]) -> str:
    normalized = {str(k).strip(): v for k, v in row.items()}
    for choice in choices:
        if choice in row and row.get(choice):
            return str(row.get(choice, ""))
        clean = choice.strip()
        if clean in normalized and normalized.get(clean):
            return str(normalized[clean])
    return ""


def percentile(values: List[float], q: float) -> float | None:
    vals = sorted(v for v in values if v == v)
    if not vals:
        return None
    idx = (len(vals) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(vals) - 1)
    frac = idx - lo
    return vals[lo] + (vals[hi] - vals[lo]) * frac


def summarize_gpu(path: Path) -> Dict[str, Any]:
    rows = read_csv(path)
    out: Dict[str, Any] = {"gpu_rows": len(rows)}
    col_map = {
        "gpu_temp_c": ["temperature.gpu [C]", "temperature.gpu"],
        "sm_clock_mhz": ["clocks.current.sm [MHz]", "clocks.sm [MHz]", "clocks.current.sm", "clocks.sm"],
        "power_w": ["power.draw [W]", "power.draw"],
        "gpu_util_pct": ["utilization.gpu [%]", "utilization.gpu"],
    }
    for name, choices in col_map.items():
        vals = []
        for row in rows:
            raw = get_cell(row, choices)
            if raw:
                vals.append(f({"value": raw}, "value"))
        out[f"{name}_median"] = percentile(vals, 0.5)
        out[f"{name}_p95"] = percentile(vals, 0.95)
    return out


def summarize_vm_sample_age(run_dir: Path) -> Dict[str, Any]:
    manifest_path = run_dir / "vm_sample_age_analysis" / "analysis_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return {
                "vm_sample_age_p95_s": manifest.get("overall_sample_age_p95_s"),
                "vm_sample_age_max_s": manifest.get("overall_sample_age_max_s"),
                "vm_sample_age_decision": manifest.get("overall_decision", ""),
            }
        except Exception:
            pass
    telemetry_path = run_dir / "telemetry_availability_summary.json"
    if telemetry_path.exists():
        try:
            telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
            return {
                "vm_sample_age_p95_s": None,
                "vm_sample_age_max_s": telemetry.get("vm_sample_age_max_s"),
                "vm_sample_age_decision": "not_checked_with_sidecar",
            }
        except Exception:
            pass
    return {"vm_sample_age_p95_s": None, "vm_sample_age_max_s": None, "vm_sample_age_decision": "missing"}


def summarize_run(run_dir: Path) -> Dict[str, Any]:
    arrival = read_csv(run_dir / "open_loop_arrival_1s_summary.csv")
    completion = read_csv(run_dir / "open_loop_completion_1s_summary.csv")
    raw = read_csv(run_dir / "open_loop_client_raw.csv")
    offered = [f(r, "offered_rps") for r in arrival]
    scheduled = sum(f(r, "scheduled_request_count") for r in arrival)
    dropped = sum(f(r, "dropped_max_inflight_count") for r in arrival)
    completed = sum(f(r, "completed_request_count") for r in completion)
    successful = sum(f(r, "successful_completion_count") for r in completion)
    timeouts = sum(f(r, "timeout_completion_count") for r in completion)
    failed = sum(f(r, "failed_completion_count") for r in completion)
    lat_p50 = [f(r, "latency_p50") for r in completion if r.get("latency_p50")]
    lat_p95 = [f(r, "latency_p95") for r in completion if r.get("latency_p95")]
    lat_p99 = [f(r, "latency_p99") for r in completion if r.get("latency_p99")]
    arrival_duration_bins = len(arrival)
    out: Dict[str, Any] = {
        "run_dir": str(run_dir),
        "raw_request_rows": len(raw),
        "arrival_duration_bins": arrival_duration_bins,
        "offered_rps_median": percentile(offered, 0.5),
        "scheduled_request_count": scheduled,
        "drop_ratio": dropped / scheduled if scheduled else None,
        "completion_throughput_rps_mean": completed / arrival_duration_bins if arrival_duration_bins else None,
        "completion_bin_completed_rps_median": percentile([f(r, "realized_completed_rps") for r in completion], 0.5),
        "completed_request_count": completed,
        "successful_completion_count": successful,
        "timeout_rate": timeouts / completed if completed else None,
        "error_rate": failed / completed if completed else None,
        "latency_p50_median": percentile(lat_p50, 0.5),
        "latency_p95_median": percentile(lat_p95, 0.5),
        "latency_p99_median": percentile(lat_p99, 0.5),
    }
    out.update(summarize_gpu(run_dir / "nvidia_smi_gpu_1s.csv"))
    out.update(summarize_vm_sample_age(run_dir))
    abort_path = run_dir / "safety_abort_record.json"
    if abort_path.exists():
        try:
            abort = json.loads(abort_path.read_text(encoding="utf-8"))
            out["abort_reason"] = abort.get("abort_reason", "")
            out["completed"] = abort.get("completed", False)
        except Exception:
            out["abort_reason"] = "abort_record_parse_error"
            out["completed"] = False
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
    root = Path(args.input_root)
    out_dir = Path(args.out_dir)
    run_dirs = [p for p in sorted(root.iterdir()) if p.is_dir() and (p / "open_loop_arrival_1s_summary.csv").exists()] if root.exists() else []
    rows = [summarize_run(p) for p in run_dirs]
    write_csv(out_dir / "normal_load_calibration_summary.csv", rows)
    report = [
        "# Normal-cooling open-loop calibration summary",
        "",
        f"- input_root: `{root}`",
        f"- candidate_runs: `{len(rows)}`",
        "",
        "此報告比較 offered load 與 realized service activity，但不自動選定 low/medium/high。completed RPS 只代表服務完成量，不是外部 demand。",
        "",
        "| offered_rps | scheduled | completed | drop_ratio | timeout_rate | error_rate | latency_p95_ms | gpu_temp_p95_c | sm_clock_median_mhz | vm_age_max_s | completed |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        report.append(
            "| "
            f"{row.get('offered_rps_median')} | "
            f"{row.get('scheduled_request_count')} | "
            f"{row.get('completed_request_count')} | "
            f"{row.get('drop_ratio')} | "
            f"{row.get('timeout_rate')} | "
            f"{row.get('error_rate')} | "
            f"{row.get('latency_p95_median')} | "
            f"{row.get('gpu_temp_c_p95')} | "
            f"{row.get('sm_clock_mhz_median')} | "
            f"{row.get('vm_sample_age_max_s')} | "
            f"{row.get('completed')} |"
        )
    report.extend(
        [
            "",
            "## 初步判讀",
            "",
            "- 本 summary 僅代表 normal-cooling first-pass calibration，不是 replicated normal high-load baseline。",
            "- 若所有 candidate 皆無 drop、timeout/error burst，且 GPU temperature 距 operator limit 仍有餘裕，可再規劃更多 replicate 或較細的 offered RPS 掃描。",
            "- 不應把 completion-binned median RPS 當外部 demand；外部 demand 以 scheduled/offered RPS 為準。",
        ]
    )
    (out_dir / "normal_load_calibration_report_zh.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (out_dir / "analysis_manifest.json").write_text(json.dumps({"input_root": str(root), "runs": len(rows)}, indent=2), encoding="utf-8")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root", required=True)
    p.add_argument("--out-dir", required=True)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
