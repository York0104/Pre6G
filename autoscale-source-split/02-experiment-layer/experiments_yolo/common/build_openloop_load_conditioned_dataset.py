#!/usr/bin/env python3
"""Build a 1s open-loop load-conditioned dataset from normal-cooling run dirs."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


VM_FEATURES = [
    "vmagg.cluster_semantic.namespace_total.cpu_cores_rate",
    "vmagg.cluster_semantic.namespace_total.memory_working_set_bytes",
    "vmagg.target_node_semantic.node_compute_features.cpu_compute.cpu_user_percent",
    "vmagg.target_node_semantic.node_compute_features.cpu_compute.load1",
    "vmagg.target_node_semantic.node_compute_features.cpu_compute.load5",
    "vmagg.target_node_semantic.node_compute_features.ram_capacity.memory_usage_percent",
    "vmagg.target_node_semantic.node_pressure_instant.cpu_usage_percent",
    "vmagg.target_node_semantic.node_pressure_instant.load_average.load1",
    "vmagg.target_node_semantic.node_pressure_instant.load_average.load5",
    "vmagg.target_node_semantic.node_pressure_instant.mem_used_bytes",
]

VM_GPU_UTIL_PENDING_FEATURE = "vmagg.target_node_semantic.gpu_bound_features.gpu_compute.gpu_util_avg"

V2_REQUIRED_MANIFEST_FIELDS = [
    "campaign_id",
    "replicate_id",
    "target_offered_rps",
    "run_order",
    "warmup_start_ts",
    "warmup_end_ts",
    "measurement_start_ts",
    "measurement_end_ts",
    "client_start_ts",
    "client_stop_ts",
    "endpoint_identity",
    "model",
    "image_set_hash",
    "node_gpu_identity",
    "background_workload_state",
    "telemetry_source_availability",
    "telemetry_sample_age_summary",
]


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def numeric_text(value: Any) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
    return float(match.group(0)) if match else None


def run_target_rps(run_dir: Path) -> float | None:
    manifest = run_dir / "run_manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            return float(data.get("offered_load_profile", {}).get("target_rps"))
        except Exception:
            pass
    match = re.search(r"rps([0-9.]+)_", run_dir.name)
    return float(match.group(1)) if match else None


def load_manifest(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / "run_manifest.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def measurement_elapsed_window(manifest: Dict[str, Any]) -> Dict[str, float | None]:
    if manifest.get("measurement_start_elapsed_s") is not None and manifest.get("measurement_end_elapsed_s") is not None:
        return {
            "measurement_start_elapsed_s": float(manifest["measurement_start_elapsed_s"]),
            "measurement_end_elapsed_s": float(manifest["measurement_end_elapsed_s"]),
        }
    client_start = parse_ts(manifest.get("client_start_ts"))
    measurement_start = parse_ts(manifest.get("measurement_start_ts"))
    measurement_end = parse_ts(manifest.get("measurement_end_ts"))
    if not client_start or not measurement_start or not measurement_end:
        return {"measurement_start_elapsed_s": None, "measurement_end_elapsed_s": None}
    return {
        "measurement_start_elapsed_s": max(0.0, (measurement_start - client_start).total_seconds()),
        "measurement_end_elapsed_s": max(0.0, (measurement_end - client_start).total_seconds()),
    }


def manifest_metadata(run_dir: Path) -> Dict[str, Any]:
    manifest = load_manifest(run_dir)
    if not isinstance(manifest, dict):
        manifest = {}
    profile = manifest.get("offered_load_profile", {}) if manifest else {}
    if not isinstance(profile, dict):
        profile = {}
    replicate = manifest.get("replicate_id")
    if replicate is None:
        replicate = profile.get("replicate")
    if replicate is None:
        replicate = manifest.get("replicate") if manifest else None
    window = measurement_elapsed_window(manifest)
    warmup = manifest.get("warmup_s", manifest.get("warm_up_s", window.get("measurement_start_elapsed_s")))
    gaps = []
    for field in V2_REQUIRED_MANIFEST_FIELDS:
        if manifest.get(field) in (None, "", {}):
            gaps.append(f"{field}_missing")
    if window.get("measurement_start_elapsed_s") is None or window.get("measurement_end_elapsed_s") is None:
        gaps.append("measurement_elapsed_window_missing")
    analysis_ineligible = bool(manifest.get("analysis_ineligible")) or bool(gaps)
    return {
        "campaign_id": manifest.get("campaign_id"),
        "replicate_id": replicate,
        "run_order": manifest.get("run_order"),
        "manifest_replicate": replicate,
        "manifest_warmup_s": warmup,
        "manifest_created_at_utc": manifest.get("created_at_utc"),
        "manifest_gap": ";".join(gaps),
        "analysis_ineligible": analysis_ineligible,
        "analysis_ineligible_reason": manifest.get("analysis_ineligible_reason") or ";".join(gaps),
        "measurement_start_elapsed_s": window.get("measurement_start_elapsed_s"),
        "measurement_end_elapsed_s": window.get("measurement_end_elapsed_s"),
        "latency_target_policy": json.dumps(manifest.get("latency_target_policy", {}), ensure_ascii=False, sort_keys=True),
        "background_workload_state": json.dumps(manifest.get("background_workload_state", manifest.get("background_workload", {})), ensure_ascii=False, sort_keys=True),
    }


def normalize_gpu(gpu: pd.DataFrame) -> pd.DataFrame:
    if gpu.empty:
        return pd.DataFrame()
    out = pd.DataFrame({"elapsed_s": range(len(gpu))})
    col_map = {
        "gpu_util_pct": ["utilization.gpu [%]", " utilization.gpu [%]", "utilization.gpu"],
        "gpu_mem_util_pct": ["utilization.memory [%]", " utilization.memory [%]", "utilization.memory"],
        "gpu_memory_used_mib": ["memory.used [MiB]", " memory.used [MiB]", "memory.used"],
        "gpu_power_w": ["power.draw [W]", " power.draw [W]", "power.draw"],
        "gpu_temp_c": ["temperature.gpu", " temperature.gpu", "temperature.gpu [C]"],
        "sm_clock_mhz": ["clocks.current.sm [MHz]", " clocks.current.sm [MHz]", "clocks.sm [MHz]"],
        "mem_clock_mhz": ["clocks.current.memory [MHz]", " clocks.current.memory [MHz]", "clocks.mem [MHz]"],
    }
    normalized = {str(c).strip(): c for c in gpu.columns}
    for name, choices in col_map.items():
        source = None
        for choice in choices:
            if choice in gpu.columns:
                source = choice
                break
            if choice.strip() in normalized:
                source = normalized[choice.strip()]
                break
        if source is not None:
            out[name] = [numeric_text(v) for v in gpu[source]]
    return out


def normalize_vm(vm: pd.DataFrame) -> pd.DataFrame:
    if vm.empty:
        return pd.DataFrame()
    out = pd.DataFrame({"elapsed_s": range(len(vm))})
    for col in VM_FEATURES:
        if col in vm.columns:
            short = "vm_" + col.replace("vmagg.", "").replace(".", "__")
            out[short] = pd.to_numeric(vm[col], errors="coerce")
    return out


def rolling_latency_targets(run_dir: Path, window_s: int, min_samples: int) -> pd.DataFrame:
    raw = read_csv(run_dir / "open_loop_client_raw.csv")
    if raw.empty or "complete_elapsed_s" not in raw.columns:
        return pd.DataFrame()
    work = raw.copy()
    work["complete_elapsed_s"] = pd.to_numeric(work["complete_elapsed_s"], errors="coerce")
    work["e2e_latency_ms"] = pd.to_numeric(work.get("e2e_latency_ms"), errors="coerce")
    if "success" in work.columns:
        success = work["success"].astype(str).str.lower().isin({"true", "1", "yes"})
        work = work[success]
    work = work.dropna(subset=["complete_elapsed_s", "e2e_latency_ms"])
    if work.empty:
        return pd.DataFrame()
    max_elapsed = int(max(0, work["complete_elapsed_s"].max()))
    rows: List[Dict[str, Any]] = []
    for elapsed_s in range(max_elapsed + 1):
        start = max(0, elapsed_s - window_s + 1)
        in_window = work[(work["complete_elapsed_s"] >= start) & (work["complete_elapsed_s"] < elapsed_s + 1)]
        values = in_window["e2e_latency_ms"].dropna()
        count = int(len(values))
        sufficient = count >= min_samples
        rows.append(
            {
                "elapsed_s": elapsed_s,
                "rolling_latency_window_s": window_s,
                "rolling_latency_min_samples": min_samples,
                "rolling_completion_count": count,
                "rolling_latency_sample_sufficient": bool(sufficient),
                "latency_quality_status": "ok" if sufficient else f"insufficient_completion_count<{min_samples}",
                "rolling_latency_p50": float(values.quantile(0.50)) if sufficient else None,
                "rolling_latency_mean": float(values.mean()) if sufficient else None,
                "rolling_latency_p95": float(values.quantile(0.95)) if sufficient else None,
                "rolling_latency_p99": float(values.quantile(0.99)) if sufficient else None,
            }
        )
    return pd.DataFrame(rows)


def run_rows(run_dir: Path, latency_window_s: int, latency_min_samples: int) -> pd.DataFrame:
    arrival = read_csv(run_dir / "open_loop_arrival_1s_summary.csv")
    completion = read_csv(run_dir / "open_loop_completion_1s_summary.csv")
    gpu = normalize_gpu(read_csv(run_dir / "nvidia_smi_gpu_1s.csv"))
    vm = normalize_vm(read_csv(run_dir / "vm_aggregator_timeseries.csv"))
    if arrival.empty:
        return pd.DataFrame()
    target_rps = run_target_rps(run_dir)
    base_cols = [
        "elapsed_s",
        "scheduled_request_count",
        "launched_request_count",
        "dropped_max_inflight_count",
        "inflight_count_max",
        "client_backlog_or_schedule_miss",
        "timeout_rate",
        "fail_rate",
    ]
    df = arrival[[c for c in base_cols if c in arrival.columns]].copy()
    df["target_offered_rps"] = target_rps
    df["cooling_condition"] = "normal_cooling"
    df["run_id"] = run_dir.name
    for key, value in manifest_metadata(run_dir).items():
        df[key] = value
    if not completion.empty:
        comp_cols = [
            "elapsed_s",
            "realized_completed_rps",
            "completed_request_count",
            "successful_completion_count",
            "completion_success_fraction",
            "completion_timeout_fraction",
            "latency_p50",
            "latency_p95",
            "latency_p99",
        ]
        comp = completion[[c for c in comp_cols if c in completion.columns]].copy()
        comp = comp.rename(columns={c: f"completion_{c}" for c in comp.columns if c != "elapsed_s"})
        df = df.merge(comp, on="elapsed_s", how="left")
    if not gpu.empty:
        df = df.merge(gpu, on="elapsed_s", how="left")
    if not vm.empty:
        df = df.merge(vm, on="elapsed_s", how="left")
    rolling = rolling_latency_targets(run_dir, latency_window_s, latency_min_samples)
    if not rolling.empty:
        df = df.merge(rolling, on="elapsed_s", how="left")
    elapsed = pd.to_numeric(df["elapsed_s"], errors="coerce")
    start = pd.to_numeric(df.get("measurement_start_elapsed_s"), errors="coerce")
    end = pd.to_numeric(df.get("measurement_end_elapsed_s"), errors="coerce")
    df["in_measurement_window"] = (elapsed >= start) & (elapsed < end)
    df["eligible_for_formal_validation"] = (~df["analysis_ineligible"].fillna(True).astype(bool)) & df["in_measurement_window"].fillna(False)
    return df


def write_manifest_gap_summary(out_dir: Path, df: pd.DataFrame) -> None:
    cols = ["run_id", "campaign_id", "replicate_id", "target_offered_rps", "manifest_gap", "analysis_ineligible", "analysis_ineligible_reason"]
    rows = df[[c for c in cols if c in df.columns]].drop_duplicates()
    rows.to_csv(out_dir / "manifest_gap_summary.csv", index=False)


def write_latency_quality_summary(out_dir: Path, df: pd.DataFrame) -> None:
    if "latency_quality_status" not in df.columns:
        pd.DataFrame(
            columns=[
                "target_offered_rps",
                "latency_quality_status",
                "rows",
                "median_completion_count",
                "eligible_rows",
            ]
        ).to_csv(out_dir / "latency_target_quality_summary.csv", index=False)
        return
    rows = (
        df.groupby(["target_offered_rps", "latency_quality_status"], dropna=False)
        .agg(
            rows=("elapsed_s", "count"),
            median_completion_count=("rolling_completion_count", "median"),
            eligible_rows=("eligible_for_formal_validation", "sum"),
        )
        .reset_index()
    )
    rows.to_csv(out_dir / "latency_target_quality_summary.csv", index=False)


def write_feature_schema_audit(out_dir: Path, df: pd.DataFrame) -> None:
    rows = [
        {"feature": "target_offered_rps", "role": "primary_external_offered_load", "decision": "allowed"},
        {"feature": "scheduled_request_count", "role": "arrival_accounting", "decision": "exclude_if_target_offered_rps_used"},
        {"feature": "launched_request_count", "role": "client_accounting", "decision": "context_or_sensitivity_only"},
        {"feature": "inflight_count_max", "role": "client_capacity_state", "decision": "allowed"},
        {"feature": "client_backlog_or_schedule_miss", "role": "client_capacity_state", "decision": "allowed"},
        {"feature": "background_workload_state", "role": "verified_background_state", "decision": "allowed_when_manifest_valid"},
        {"feature": "gpu_util_pct", "role": "nvidia_smi_gpu_state_reference", "decision": "reference_not_primary_external_load"},
        {"feature": "sm_clock_mhz", "role": "gpu_state_or_target", "decision": "target_or_reference_not_load_predictor"},
        {"feature": VM_GPU_UTIL_PENDING_FEATURE, "role": "telemetry_semantic_pending", "decision": "exclude_primary_feature"},
    ]
    for row in rows:
        short = "vm_" + row["feature"].replace("vmagg.", "").replace(".", "__") if row["feature"].startswith("vmagg.") else row["feature"]
        row["present_in_dataset"] = short in df.columns or row["feature"] in df.columns
    pd.DataFrame(rows).to_csv(out_dir / "feature_schema_audit.csv", index=False)


def run(args: argparse.Namespace) -> int:
    root = Path(args.input_root)
    out_dir = Path(args.out_dir)
    run_dirs = [
        p
        for p in sorted(root.iterdir())
        if p.is_dir() and (p / "open_loop_arrival_1s_summary.csv").exists()
    ]
    frames = [run_rows(p, args.latency_rolling_window_s, args.latency_min_samples) for p in run_dirs]
    frames = [f for f in frames if not f.empty]
    if not frames:
        raise RuntimeError(f"no open-loop run dirs found under {root}")
    df = pd.concat(frames, ignore_index=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset = out_dir / "openloop_load_conditioned_1s_dataset.csv"
    df.to_csv(dataset, index=False)
    write_manifest_gap_summary(out_dir, df)
    write_latency_quality_summary(out_dir, df)
    write_feature_schema_audit(out_dir, df)
    manifest = {
        "input_root": str(root),
        "dataset": str(dataset),
        "runs": len(frames),
        "rows": int(len(df)),
        "vm_features_requested": VM_FEATURES,
        "vm_features_excluded_pending_semantic_validation": [VM_GPU_UTIL_PENDING_FEATURE],
        "rolling_latency_window_s": args.latency_rolling_window_s,
        "rolling_latency_min_samples": args.latency_min_samples,
        "columns": list(df.columns),
        "notes": "normal-cooling only; no phase/fan/intervention features included; VM gpu_util_avg excluded pending semantic validation",
    }
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--latency-rolling-window-s", type=int, default=10)
    p.add_argument("--latency-min-samples", type=int, default=5)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
