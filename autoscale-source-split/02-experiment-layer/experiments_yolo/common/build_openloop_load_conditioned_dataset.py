#!/usr/bin/env python3
"""Build a 1s open-loop load-conditioned dataset from normal-cooling run dirs."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


VM_FEATURES = [
    "vmagg.cluster_semantic.namespace_total.cpu_cores_rate",
    "vmagg.cluster_semantic.namespace_total.memory_working_set_bytes",
    "vmagg.target_node_semantic.gpu_bound_features.gpu_compute.gpu_util_avg",
    "vmagg.target_node_semantic.node_compute_features.cpu_compute.cpu_user_percent",
    "vmagg.target_node_semantic.node_compute_features.cpu_compute.load1",
    "vmagg.target_node_semantic.node_compute_features.cpu_compute.load5",
    "vmagg.target_node_semantic.node_compute_features.ram_capacity.memory_usage_percent",
    "vmagg.target_node_semantic.node_pressure_instant.cpu_usage_percent",
    "vmagg.target_node_semantic.node_pressure_instant.load_average.load1",
    "vmagg.target_node_semantic.node_pressure_instant.load_average.load5",
    "vmagg.target_node_semantic.node_pressure_instant.mem_used_bytes",
]


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


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


def run_rows(run_dir: Path) -> pd.DataFrame:
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
    return df


def run(args: argparse.Namespace) -> int:
    root = Path(args.input_root)
    out_dir = Path(args.out_dir)
    run_dirs = [
        p
        for p in sorted(root.iterdir())
        if p.is_dir() and (p / "open_loop_arrival_1s_summary.csv").exists()
    ]
    frames = [run_rows(p) for p in run_dirs]
    frames = [f for f in frames if not f.empty]
    if not frames:
        raise RuntimeError(f"no open-loop run dirs found under {root}")
    df = pd.concat(frames, ignore_index=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset = out_dir / "openloop_load_conditioned_1s_dataset.csv"
    df.to_csv(dataset, index=False)
    manifest = {
        "input_root": str(root),
        "dataset": str(dataset),
        "runs": len(frames),
        "rows": int(len(df)),
        "vm_features_requested": VM_FEATURES,
        "columns": list(df.columns),
        "notes": "normal-cooling only; no phase/fan/intervention features included",
    }
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root", required=True)
    p.add_argument("--out-dir", required=True)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
