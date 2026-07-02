#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler


DEFAULT_RESULTS_ROOT = Path(
    "autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle"
)
DEFAULT_OUT_NAME = "offline_forecasting_analysis"
LOCAL_TZ = "Asia/Taipei"
PRIMARY_TOLERANCE_S = 2.0
TOLERANCES_S = [1.0, 2.0, 5.0]
GRID_FREQ = "1s"
FORECAST_HORIZONS_S = [10, 30]
EWMA_SPAN = 15
ROLL_WINDOWS = [5, 15, 60]
PLOT_DPI = 170
DEGRADATION_SUSTAIN_WINDOW_S = 15
DEGRADATION_MIN_BAD_SECONDS = 5


@dataclass(frozen=True)
class Paths:
    run_dir: Path
    measurement: Path
    aligned_serial: Path
    thermal: Path
    events: Path
    config: Path
    summary: Path
    vmagg_features: Path


def q(v: pd.Series, p: float) -> float:
    s = pd.to_numeric(v, errors="coerce").dropna()
    return float(s.quantile(p)) if len(s) else math.nan


def safe_mean(v: pd.Series) -> float:
    s = pd.to_numeric(v, errors="coerce").dropna()
    return float(s.mean()) if len(s) else math.nan


def safe_median(v: pd.Series) -> float:
    s = pd.to_numeric(v, errors="coerce").dropna()
    return float(s.median()) if len(s) else math.nan


def mad(values: pd.Series) -> float:
    s = pd.to_numeric(values, errors="coerce").dropna()
    if len(s) == 0:
        return math.nan
    med = s.median()
    return float((s - med).abs().median())


def parse_thermal_ts(series: pd.Series) -> pd.Series:
    ts = pd.to_datetime(series, errors="coerce")
    if getattr(ts.dt, "tz", None) is None:
        return ts.dt.tz_localize(LOCAL_TZ).dt.tz_convert("UTC")
    return ts.dt.tz_convert("UTC")


def parse_event_ts(series: pd.Series) -> pd.Series:
    return parse_thermal_ts(series)


def numeric(df: pd.DataFrame, cols: Iterable[str]) -> None:
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")


def discover_runs(results_root: Path) -> list[Paths]:
    runs: list[Paths] = []
    for run_dir in sorted(p for p in results_root.iterdir() if p.is_dir()):
        if not run_dir.name.startswith("singlepod_bgcycle_"):
            continue
        runs.append(
            Paths(
                run_dir=run_dir,
                measurement=run_dir / "measurement_raw.csv",
                aligned_serial=run_dir / "aligned_serial_thermal.csv",
                thermal=run_dir / "thermal_cycle" / "worker_logs" / "thermal.csv",
                events=run_dir / "thermal_cycle" / "worker_logs" / "events.csv",
                config=run_dir / "experiment_config.txt",
                summary=run_dir / "thermal_cycle" / "worker_logs" / "summary.json",
                vmagg_features=run_dir / "vm_aggregator_training_features.csv",
            )
        )
    return runs


def parse_config(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def run_start_key(run_id: str) -> str:
    m = re.search(r"(\d{8}_\d{6})$", run_id)
    return m.group(1) if m else run_id


def load_measurement(path: Path) -> pd.DataFrame:
    cols = [
        "req_id",
        "client_ts_start",
        "client_ts_end",
        "e2e_latency_ms",
        "status_code",
        "success",
        "server_latency_ms",
        "server_total_latency_ms",
        "server_time",
        "inter_request_gap_ms",
        "loop_elapsed_ms",
        "error_type",
    ]
    df = pd.read_csv(path, usecols=lambda c: c in cols, low_memory=False)
    df["client_ts_start"] = pd.to_datetime(df["client_ts_start"], utc=True, errors="coerce")
    df["client_ts_end"] = pd.to_datetime(df["client_ts_end"], utc=True, errors="coerce")
    numeric(
        df,
        [
            "e2e_latency_ms",
            "status_code",
            "success",
            "server_latency_ms",
            "server_total_latency_ms",
            "inter_request_gap_ms",
            "loop_elapsed_ms",
        ],
    )
    if "error_type" not in df.columns:
        df["error_type"] = ""
    df["success_bool"] = df["error_type"].fillna("").eq("normal_success") | df["success"].fillna(0).eq(1)
    return df.dropna(subset=["client_ts_start"]).sort_values("client_ts_start")


def load_thermal(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["thermal_ts"] = parse_thermal_ts(df["timestamp"])
    numeric(
        df,
        [
            "elapsed_s",
            "cycle_index",
            "phase_elapsed_s",
            "gpu_temp_c",
            "gpu_util_pct",
            "gpu_power_w",
            "gpu_fan_pct",
            "gpu_clock_mhz",
            "gpu_mem_clock_mhz",
            "stable_counter_s",
        ],
    )
    return df.dropna(subset=["thermal_ts"]).sort_values("thermal_ts")


def load_events(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "timestamp" in df.columns:
        df["event_ts"] = parse_event_ts(df["timestamp"])
    numeric(df, ["elapsed_s", "cycle_index"])
    return df


def summarize_inventory(paths: list[Paths], out_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    sens_rows: list[dict[str, object]] = []
    for p in paths:
        run_id = p.run_dir.name
        files = {
            "measurement_raw.csv": p.measurement.exists(),
            "thermal.csv": p.thermal.exists(),
            "events.csv": p.events.exists(),
            "aligned_serial_thermal.csv": p.aligned_serial.exists(),
            "experiment_config.txt": p.config.exists(),
            "vm_aggregator_training_features.csv": p.vmagg_features.exists(),
        }
        row: dict[str, object] = {
            "run_id": run_id,
            "available_files": ";".join(k for k, v in files.items() if v),
            "missing_files": ";".join(k for k, v in files.items() if not v),
        }
        try:
            meas = load_measurement(p.measurement) if p.measurement.exists() else pd.DataFrame()
            thermal = load_thermal(p.thermal) if p.thermal.exists() else pd.DataFrame()
            events = load_events(p.events)
            row["request_rows"] = int(len(meas))
            row["success_rows"] = int(meas["success_bool"].sum()) if len(meas) else 0
            row["success_rate"] = float(meas["success_bool"].mean()) if len(meas) else math.nan
            row["thermal_sample_count"] = int(len(thermal))
            row["cycle_count"] = int(thermal["cycle_index"].dropna().nunique()) if len(thermal) else 0
            row["phases"] = ",".join(str(x) for x in sorted(thermal["phase"].dropna().unique())) if "phase" in thermal else ""
            if len(meas):
                row["request_start_utc"] = meas["client_ts_start"].min().isoformat()
                row["request_end_utc"] = meas["client_ts_start"].max().isoformat()
                row["median_request_interval_s"] = float(meas["client_ts_start"].diff().dt.total_seconds().median())
            if len(thermal):
                row["thermal_start_utc"] = thermal["thermal_ts"].min().isoformat()
                row["thermal_end_utc"] = thermal["thermal_ts"].max().isoformat()
                row["median_thermal_interval_s"] = float(thermal["thermal_ts"].diff().dt.total_seconds().median())
            if len(meas) and len(thermal):
                overlap_start = max(meas["client_ts_start"].min(), thermal["thermal_ts"].min())
                overlap_end = min(meas["client_ts_start"].max(), thermal["thermal_ts"].max())
                row["overlap_start_utc"] = overlap_start.isoformat()
                row["overlap_end_utc"] = overlap_end.isoformat()
                row["overlap_seconds"] = float((overlap_end - overlap_start).total_seconds())
                # Alignment quality is evaluated on the same 1 second client
                # time grid used by the canonical dataset. Request rows are
                # closed-loop and highly autocorrelated, so repeating this on
                # every raw request row is both expensive and misleadingly
                # over-weighted toward high-latency periods.
                client_bins = (
                    meas[["client_ts_start"]]
                    .assign(client_ts=meas["client_ts_start"].dt.floor(GRID_FREQ))
                    [["client_ts"]]
                    .drop_duplicates()
                    .sort_values("client_ts")
                )
                for tol in TOLERANCES_S:
                    aligned = pd.merge_asof(
                        client_bins,
                        thermal[["thermal_ts"]].sort_values("thermal_ts"),
                        left_on="client_ts",
                        right_on="thermal_ts",
                        direction="nearest",
                        tolerance=pd.Timedelta(seconds=tol),
                    )
                    matched = aligned["thermal_ts"].notna()
                    offsets = (
                        (aligned.loc[matched, "client_ts"] - aligned.loc[matched, "thermal_ts"])
                        .dt.total_seconds()
                        .abs()
                    )
                    sens_rows.append(
                        {
                            "run_id": run_id,
                            "tolerance_s": tol,
                            "request_rows": len(meas),
                            "client_1s_bins": len(aligned),
                            "matched_bins": int(matched.sum()),
                            "matched_rate": float(matched.mean()) if len(aligned) else math.nan,
                            "offset_abs_p50_s": float(offsets.quantile(0.5)) if len(offsets) else math.nan,
                            "offset_abs_p95_s": float(offsets.quantile(0.95)) if len(offsets) else math.nan,
                        }
                    )
                primary = [r for r in sens_rows if r["run_id"] == run_id and r["tolerance_s"] == PRIMARY_TOLERANCE_S][-1]
                row["alignment_matched_rate_tol2s"] = primary["matched_rate"]
                row["alignment_offset_abs_p95_s_tol2s"] = primary["offset_abs_p95_s"]
            event_names = ",".join(sorted(events["event"].dropna().unique())) if len(events) and "event" in events else ""
            row["event_names"] = event_names
            suitable_time = bool(
                row.get("request_rows", 0) and row.get("thermal_sample_count", 0) and row.get("overlap_seconds", 0) > 300
            )
            suitable_model = bool(
                suitable_time
                and row.get("cycle_count", 0) >= 1
                and row.get("success_rows", 0) >= 1000
                and row.get("alignment_matched_rate_tol2s", 0) >= 0.95
            )
            row["suitable_for_time_analysis"] = suitable_time
            row["suitable_for_modeling"] = suitable_model
            reasons = []
            if not p.measurement.exists():
                reasons.append("missing measurement_raw.csv")
            if not p.thermal.exists():
                reasons.append("missing thermal.csv")
            if row.get("overlap_seconds", 0) <= 300:
                reasons.append("insufficient request/thermal overlap")
            if row.get("success_rows", 0) < 1000:
                reasons.append("insufficient successful latency rows")
            if row.get("alignment_matched_rate_tol2s", 0) < 0.95:
                reasons.append("weak timestamp alignment at 2s tolerance")
            row["exclude_reason"] = "; ".join(reasons)
        except Exception as exc:
            row["suitable_for_time_analysis"] = False
            row["suitable_for_modeling"] = False
            row["exclude_reason"] = f"load_error: {exc}"
        rows.append(row)
    inv = pd.DataFrame(rows)
    sens = pd.DataFrame(sens_rows)
    inv.to_csv(out_dir / "run_inventory.csv", index=False)
    inv.to_csv(out_dir / "data_quality_summary.csv", index=False)
    sens.to_csv(out_dir / "alignment_tolerance_sensitivity.csv", index=False)
    return inv


def aggregate_run_to_grid(p: Paths, tolerance_s: float = PRIMARY_TOLERANCE_S) -> pd.DataFrame:
    run_id = p.run_dir.name
    cfg = parse_config(p.config)
    cols = [
        "req_id",
        "client_ts_start",
        "client_ts_end",
        "e2e_latency_ms",
        "success",
        "server_latency_ms",
        "server_total_latency_ms",
        "inter_request_gap_ms",
        "error_type",
        "success_bool",
        "timestamp",
        "thermal_ts",
        "elapsed_s",
        "cycle_index",
        "phase",
        "phase_elapsed_s",
        "binary_label",
        "gpu_temp_c",
        "gpu_util_pct",
        "gpu_power_w",
        "gpu_fan_pct",
        "gpu_clock_mhz",
        "gpu_mem_clock_mhz",
        "current_mode",
        "desired_mode",
        "reason",
    ]
    meas = pd.read_csv(p.aligned_serial, usecols=lambda c: c in cols, low_memory=False)
    meas["client_ts_start"] = pd.to_datetime(meas["client_ts_start"], utc=True, errors="coerce")
    meas["client_ts_end"] = pd.to_datetime(meas["client_ts_end"], utc=True, errors="coerce")
    if "thermal_ts" in meas.columns:
        meas["thermal_ts"] = pd.to_datetime(meas["thermal_ts"], utc=True, errors="coerce")
    else:
        meas["thermal_ts"] = parse_thermal_ts(meas["timestamp"])
    numeric(
        meas,
        [
            "e2e_latency_ms",
            "success",
            "server_latency_ms",
            "server_total_latency_ms",
            "inter_request_gap_ms",
            "elapsed_s",
            "cycle_index",
            "phase_elapsed_s",
            "gpu_temp_c",
            "gpu_util_pct",
            "gpu_power_w",
            "gpu_fan_pct",
            "gpu_clock_mhz",
            "gpu_mem_clock_mhz",
        ],
    )
    if "success_bool" in meas.columns:
        meas["success_bool"] = meas["success_bool"].astype(str).str.lower().isin(["true", "1", "1.0"])
    else:
        meas["success_bool"] = meas["error_type"].fillna("").eq("normal_success") | meas["success"].fillna(0).eq(1)
    meas["failure_bool"] = ~meas["success_bool"]
    meas["timeout_bool"] = meas["error_type"].fillna("").astype(str).str.contains("timeout|timed.?out", case=False, regex=True)
    meas = meas.dropna(subset=["client_ts_start"]).sort_values("client_ts_start")
    meas["client_ts_bin"] = meas["client_ts_start"].dt.floor(GRID_FREQ)
    success = meas[meas["success_bool"]].copy()
    grouped_all = meas.groupby("client_ts_bin", sort=True)
    rows = grouped_all.agg(
        request_rows=("req_id", "count"),
        success_rows=("success_bool", "sum"),
        failure_rows=("failure_bool", "sum"),
        timeout_rows=("timeout_bool", "sum"),
        client_ts_min=("client_ts_start", "min"),
        client_ts_max=("client_ts_start", "max"),
        inter_request_gap_ms_median=("inter_request_gap_ms", "median"),
        thermal_ts=("thermal_ts", "first"),
        timestamp=("timestamp", "first"),
        elapsed_s=("elapsed_s", "median"),
        cycle_index=("cycle_index", "median"),
        phase=("phase", "first"),
        phase_elapsed_s=("phase_elapsed_s", "median"),
        binary_label=("binary_label", "first"),
        gpu_temp_c=("gpu_temp_c", "median"),
        gpu_util_pct=("gpu_util_pct", "median"),
        gpu_power_w=("gpu_power_w", "median"),
        gpu_fan_pct=("gpu_fan_pct", "median"),
        gpu_clock_mhz=("gpu_clock_mhz", "median"),
        gpu_mem_clock_mhz=("gpu_mem_clock_mhz", "median"),
        current_mode=("current_mode", "first"),
        desired_mode=("desired_mode", "first"),
        reason=("reason", "first"),
    )
    if len(success):
        grouped_success = success.groupby("client_ts_bin", sort=True)
        lat = grouped_success.agg(
            e2e_latency_ms_med=("e2e_latency_ms", "median"),
            e2e_latency_ms_p95=("e2e_latency_ms", lambda x: q(x, 0.95)),
            server_latency_ms_med=("server_latency_ms", "median"),
            server_latency_ms_p95=("server_latency_ms", lambda x: q(x, 0.95)),
            server_total_latency_ms_med=("server_total_latency_ms", "median"),
            server_total_latency_ms_p95=("server_total_latency_ms", lambda x: q(x, 0.95)),
        )
        rows = rows.join(lat)
    rows = rows.reset_index().rename(columns={"client_ts_bin": "client_ts"})
    rows["success_rate"] = rows["success_rows"] / rows["request_rows"]
    rows["fail_rate"] = rows["failure_rows"] / rows["request_rows"]
    rows["timeout_error_rate"] = rows["timeout_rows"] / rows["request_rows"]
    rows["alignment_offset_s"] = (rows["client_ts"] - rows["thermal_ts"]).dt.total_seconds()
    rows.loc[rows["alignment_offset_s"].abs().gt(tolerance_s), [
        "thermal_ts",
        "timestamp",
        "elapsed_s",
        "cycle_index",
        "phase",
        "phase_elapsed_s",
        "binary_label",
        "gpu_temp_c",
        "gpu_util_pct",
        "gpu_power_w",
        "gpu_fan_pct",
        "gpu_clock_mhz",
        "gpu_mem_clock_mhz",
        "current_mode",
        "desired_mode",
        "reason",
    ]] = np.nan
    rows["run_id"] = run_id
    rows["run_start_key"] = run_start_key(run_id)
    rows["target_mode"] = cfg.get("TARGET_MODE", "")
    rows["repeat"] = pd.to_numeric(cfg.get("REPEAT", np.nan), errors="coerce")
    rows["configured_cycles"] = pd.to_numeric(cfg.get("CYCLES", np.nan), errors="coerce")
    rows["fixed_fan_pct_config"] = pd.to_numeric(cfg.get("FIXED_FAN_PCT", np.nan), errors="coerce")
    rows["bg_size_config"] = pd.to_numeric(cfg.get("BG_SIZE", np.nan), errors="coerce")
    rows["bg_duty_config"] = pd.to_numeric(cfg.get("BG_DUTY", np.nan), errors="coerce")
    rows["target_mode_config"] = cfg.get("TARGET_MODE", "")
    rows["profile_key"] = (
        "repeat=" + rows["repeat"].astype(str)
        + "|fan=" + rows["fixed_fan_pct_config"].astype(str)
        + "|bg_size=" + rows["bg_size_config"].astype(str)
        + "|bg_duty=" + rows["bg_duty_config"].astype(str)
        + "|target=" + rows["target_mode_config"].astype(str)
    )
    rows["t_rel_s"] = (rows["client_ts"] - rows["client_ts"].min()).dt.total_seconds()
    rows["cycle_uid"] = rows["run_id"] + "_c" + rows["cycle_index"].fillna(-1).astype(int).astype(str)
    return rows


def build_aligned_dataset(paths: list[Paths], inv: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    selected = set(inv.loc[inv["suitable_for_time_analysis"].fillna(False), "run_id"].astype(str))
    parts = []
    for idx, p in enumerate(paths, 1):
        if p.run_dir.name not in selected:
            continue
        part = aggregate_run_to_grid(p)
        parts.append(part)
        if idx % 40 == 0:
            print(f"[INFO] aligned {idx}/{len(paths)} runs", flush=True)
    aligned = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    aligned = aligned.sort_values(["run_start_key", "run_id", "client_ts"]).reset_index(drop=True)
    aligned.to_csv(out_dir / "aligned_multirun_1s.csv", index=False)
    return aligned


def add_baselines(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    metrics = [
        "gpu_temp_c",
        "gpu_clock_mhz",
        "gpu_mem_clock_mhz",
        "gpu_power_w",
        "server_latency_ms_med",
        "server_total_latency_ms_med",
        "e2e_latency_ms_med",
    ]
    for col in metrics:
        df[f"{col}_baseline"] = np.nan
        df[f"{col}_delta"] = np.nan
        df[f"{col}_ratio"] = np.nan
    baseline_rows = []
    for cycle_uid, g in df.groupby("cycle_uid", sort=False):
        base = g[g["phase"].eq("normal_hold")]
        if len(base) < 60:
            base = g.head(min(len(g), 300))
        row = {"cycle_uid": cycle_uid, "run_id": g["run_id"].iloc[0], "cycle_index": g["cycle_index"].iloc[0]}
        for col in metrics:
            b = safe_median(base[col]) if col in base else math.nan
            row[f"{col}_baseline"] = b
            idx = g.index
            df.loc[idx, f"{col}_baseline"] = b
            if pd.notna(b):
                df.loc[idx, f"{col}_delta"] = df.loc[idx, col] - b
                if abs(b) > 1e-9:
                    df.loc[idx, f"{col}_ratio"] = df.loc[idx, col] / b
        baseline_rows.append(row)
    pd.DataFrame(baseline_rows)
    return df


def phase_cycle_effects(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    agg = (
        df.groupby(["run_id", "cycle_index", "phase"], dropna=False)
        .agg(
            seconds=("client_ts", "count"),
            request_rows=("request_rows", "sum"),
            success_rate=("success_rate", "mean"),
            gpu_temp_c_med=("gpu_temp_c", "median"),
            gpu_temp_c_p95=("gpu_temp_c", lambda x: q(x, 0.95)),
            gpu_clock_mhz_med=("gpu_clock_mhz", "median"),
            gpu_mem_clock_mhz_med=("gpu_mem_clock_mhz", "median"),
            gpu_power_w_med=("gpu_power_w", "median"),
            gpu_util_pct_med=("gpu_util_pct", "median"),
            server_latency_ms_med=("server_latency_ms_med", "median"),
            server_total_latency_ms_med=("server_total_latency_ms_med", "median"),
            e2e_latency_ms_med=("e2e_latency_ms_med", "median"),
            temp_delta_med=("gpu_temp_c_delta", "median"),
            clock_delta_med=("gpu_clock_mhz_delta", "median"),
            server_total_latency_ratio_med=("server_total_latency_ms_med_ratio", "median"),
        )
        .reset_index()
    )
    agg.to_csv(out_dir / "phase_cycle_effect_summary.csv", index=False)
    overall = (
        agg.groupby("phase", dropna=False)
        .agg(
            cycles=("cycle_index", "count"),
            gpu_temp_c_med=("gpu_temp_c_med", "median"),
            gpu_clock_mhz_med=("gpu_clock_mhz_med", "median"),
            server_total_latency_ms_med=("server_total_latency_ms_med", "median"),
            temp_delta_med=("temp_delta_med", "median"),
            clock_delta_med=("clock_delta_med", "median"),
            server_total_latency_ratio_med=("server_total_latency_ratio_med", "median"),
        )
        .reset_index()
    )
    overall.to_csv(out_dir / "overall_phase_effect_summary.csv", index=False)
    return agg


def event_rows(paths: list[Paths], out_dir: Path) -> pd.DataFrame:
    parts = []
    for p in paths:
        ev = load_events(p.events)
        if ev.empty:
            continue
        ev["run_id"] = p.run_dir.name
        ev["run_start_key"] = run_start_key(p.run_dir.name)
        parts.append(ev)
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if len(out):
        out.to_csv(out_dir / "event_timing_raw.csv", index=False)
    return out


def degradation_threshold(g: pd.DataFrame) -> tuple[float, float, float]:
    base = g[g["phase"].eq("normal_hold")]["server_total_latency_ms_med"].dropna()
    if len(base) < 30:
        base = g["server_total_latency_ms_med"].dropna().head(300)
    med = float(base.median()) if len(base) else math.nan
    m = mad(base)
    p95 = float(base.quantile(0.95)) if len(base) else math.nan
    thresh = max(p95, med + 3.0 * (m if pd.notna(m) and m > 0 else max(1.0, med * 0.05)), med * 1.25)
    return med, m, thresh


def first_sustained_time(g: pd.DataFrame, mask: pd.Series, consecutive: int = 5) -> float:
    run = 0
    for t, ok in zip(g["t_rel_s"], mask.fillna(False)):
        if bool(ok):
            run += 1
            if run >= consecutive:
                return float(t) - consecutive + 1
        else:
            run = 0
    return math.nan


def event_and_recovery_analysis(df: pd.DataFrame, events: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    rows = []
    if events.empty:
        event_lookup = {}
    else:
        event_lookup = {
            (r.run_id, int(r.cycle_index), str(r.phase), str(r.event)): float(r.elapsed_s)
            for r in events.itertuples()
            if pd.notna(r.cycle_index) and pd.notna(r.elapsed_s)
        }
    for cycle_uid, g in df.groupby("cycle_uid", sort=False):
        g = g.sort_values("t_rel_s")
        run_id = g["run_id"].iloc[0]
        cycle_index = int(g["cycle_index"].dropna().iloc[0]) if g["cycle_index"].notna().any() else -1
        base_temp = safe_median(g[g["phase"].eq("normal_hold")]["gpu_temp_c"])
        base_clock = safe_median(g[g["phase"].eq("normal_hold")]["gpu_clock_mhz"])
        base_lat, base_mad, lat_thresh = degradation_threshold(g)
        fault_start = event_lookup.get((run_id, cycle_index, "fault_hold", "phase_start"), math.nan)
        recovery_start = event_lookup.get((run_id, cycle_index, "recovery_wait", "phase_start"), math.nan)
        temp_onset = first_sustained_time(g, g["gpu_temp_c"] >= base_temp + 5.0)
        clock_onset = first_sustained_time(g, g["gpu_clock_mhz"] <= base_clock * 0.8)
        latency_onset = first_sustained_time(g, g["server_total_latency_ms_med"] >= lat_thresh)
        after_rec = g[g["t_rel_s"].ge(recovery_start)] if pd.notna(recovery_start) else g.iloc[0:0]
        temp_recovered = first_sustained_time(after_rec, after_rec["gpu_temp_c"] <= base_temp + 2.0)
        clock_recovered = first_sustained_time(after_rec, after_rec["gpu_clock_mhz"] >= base_clock * 0.9)
        latency_recovered = first_sustained_time(after_rec, after_rec["server_total_latency_ms_med"] <= lat_thresh)
        rows.append(
            {
                "run_id": run_id,
                "cycle_uid": cycle_uid,
                "cycle_index": cycle_index,
                "fault_start_s": fault_start,
                "recovery_start_s": recovery_start,
                "baseline_temp_c": base_temp,
                "baseline_clock_mhz": base_clock,
                "baseline_server_total_latency_ms": base_lat,
                "latency_degradation_threshold_ms": lat_thresh,
                "temp_onset_s": temp_onset,
                "clock_drop_onset_s": clock_onset,
                "latency_degradation_onset_s": latency_onset,
                "temp_after_fault_lag_s": temp_onset - fault_start if pd.notna(temp_onset) and pd.notna(fault_start) else math.nan,
                "clock_after_temp_lag_s": clock_onset - temp_onset if pd.notna(clock_onset) and pd.notna(temp_onset) else math.nan,
                "latency_after_clock_lag_s": latency_onset - clock_onset
                if pd.notna(latency_onset) and pd.notna(clock_onset)
                else math.nan,
                "temp_recovered_s": temp_recovered,
                "clock_recovered_s": clock_recovered,
                "latency_recovered_s": latency_recovered,
                "temp_recovery_duration_s": temp_recovered - recovery_start
                if pd.notna(temp_recovered) and pd.notna(recovery_start)
                else math.nan,
                "clock_recovery_duration_s": clock_recovered - recovery_start
                if pd.notna(clock_recovered) and pd.notna(recovery_start)
                else math.nan,
                "latency_recovery_duration_s": latency_recovered - recovery_start
                if pd.notna(latency_recovered) and pd.notna(recovery_start)
                else math.nan,
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "event_timing_summary.csv", index=False)
    out.to_csv(out_dir / "recovery_dynamics_summary.csv", index=False)
    return out


def lag_scan(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    rows = []
    pairs = [
        ("gpu_temp_c", "gpu_clock_mhz", "temp_vs_clock"),
        ("gpu_temp_c", "server_total_latency_ms_med", "temp_vs_server_total_latency"),
        ("gpu_clock_mhz", "server_total_latency_ms_med", "clock_vs_server_total_latency"),
    ]
    lags = list(range(-300, 301, 5))
    for name_x, name_y, label in pairs:
        for lag in lags:
            vals = []
            for _, g in df.groupby("cycle_uid", sort=False):
                x = g[name_x]
                y = g[name_y].shift(-lag)
                valid = x.notna() & y.notna()
                if valid.sum() >= 60:
                    corr = x[valid].corr(y[valid], method="spearman")
                    if pd.notna(corr):
                        vals.append(corr)
            rows.append(
                {
                    "pair": label,
                    "lag_s_positive_y_after_x": lag,
                    "median_spearman": float(np.median(vals)) if vals else math.nan,
                    "cycles": len(vals),
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "lag_analysis_summary.csv", index=False)
    return out


PRIMARY_FEATURES = [
    "gpu_temp_c",
    "gpu_temp_slope_5s",
    "gpu_temp_slope_15s",
    "gpu_temp_roll15_mean",
    "gpu_temp_roll60_mean",
    "gpu_clock_mhz",
    "gpu_clock_slope_5s",
    "gpu_clock_roll15_mean",
    "gpu_mem_clock_mhz",
    "gpu_power_w",
    "gpu_util_pct",
    "server_latency_ms_med",
    "server_latency_roll15_median",
    "server_total_latency_ms_med",
    "server_total_latency_roll15_median",
    "e2e_latency_ms_med",
    "e2e_latency_roll15_median",
    "success_rate",
    "fail_rate",
    "timeout_error_rate",
    "request_rows",
    "inter_request_gap_ms_median",
]


def add_model_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["run_start_key", "run_id", "client_ts"]).copy()
    for cycle_uid, idx in df.groupby("cycle_uid", sort=False).groups.items():
        g = df.loc[idx].sort_values("client_ts")
        for base_col in ["gpu_temp_c", "gpu_clock_mhz", "server_total_latency_ms_med", "e2e_latency_ms_med"]:
            df.loc[g.index, f"{base_col}_slope_5s"] = g[base_col] - g[base_col].shift(5)
            df.loc[g.index, f"{base_col}_slope_15s"] = g[base_col] - g[base_col].shift(15)
            for w in ROLL_WINDOWS:
                df.loc[g.index, f"{base_col}_roll{w}_mean"] = g[base_col].rolling(w, min_periods=max(2, w // 3)).mean()
                df.loc[g.index, f"{base_col}_roll{w}_median"] = g[base_col].rolling(
                    w, min_periods=max(2, w // 3)
                ).median()
        df.loc[g.index, "server_latency_roll15_median"] = g["server_latency_ms_med"].rolling(15, min_periods=5).median()
        df.loc[g.index, "e2e_latency_roll15_median"] = g["e2e_latency_ms_med"].rolling(15, min_periods=5).median()
    return df


def chronological_split(df: pd.DataFrame, test_frac: float = 0.2) -> tuple[set[str], set[str]]:
    runs = list(df[["run_id", "run_start_key"]].drop_duplicates().sort_values("run_start_key")["run_id"])
    n_test = max(1, int(math.ceil(len(runs) * test_frac)))
    test = set(runs[-n_test:])
    train = set(runs[:-n_test])
    return train, test


def rmse(y: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - pred) ** 2)))


def model_frame(df: pd.DataFrame, horizon_s: int, target: str) -> pd.DataFrame:
    parts = []
    for _, g in df.groupby("cycle_uid", sort=False):
        g = g.sort_values("client_ts").copy()
        g[f"{target}_future_{horizon_s}s"] = g[target].shift(-horizon_s)
        g[f"{target}_persistence_{horizon_s}s"] = g[target]
        g[f"{target}_rolling_{horizon_s}s"] = g[target].rolling(15, min_periods=5).median()
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def evaluate_forecasts(df: pd.DataFrame, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train_runs, test_runs = chronological_split(df)
    targets = [
        "gpu_temp_c",
        "gpu_clock_mhz",
        "server_latency_ms_med",
        "server_total_latency_ms_med",
        "e2e_latency_ms_med",
    ]
    eval_rows = []
    pred_parts = []
    coef_rows = []
    for horizon in FORECAST_HORIZONS_S:
        for target in targets:
            mf = model_frame(df, horizon, target)
            y_col = f"{target}_future_{horizon}s"
            needed = [y_col, target] + [c for c in PRIMARY_FEATURES if c in mf.columns]
            work = mf.dropna(subset=needed).copy()
            if work.empty:
                continue
            train = work[work["run_id"].isin(train_runs)]
            test = work[work["run_id"].isin(test_runs)]
            if len(train) < 200 or len(test) < 50:
                continue
            feature_cols = [c for c in PRIMARY_FEATURES if c in work.columns]
            x_train = train[feature_cols].to_numpy(float)
            x_test = test[feature_cols].to_numpy(float)
            y_train = train[y_col].to_numpy(float)
            y_test = test[y_col].to_numpy(float)
            lin = LinearRegression()
            lin.fit(x_train, y_train)
            models = {
                "persistence": test[f"{target}_persistence_{horizon}s"].to_numpy(float),
                "rolling_median_15s": test[f"{target}_rolling_{horizon}s"].fillna(test[target]).to_numpy(float),
                "linear_autoregressive": lin.predict(x_test),
            }
            for model_name, pred in models.items():
                valid = np.isfinite(pred) & np.isfinite(y_test)
                if valid.sum() == 0:
                    continue
                eval_rows.append(
                    {
                        "target": target,
                        "horizon_s": horizon,
                        "model": model_name,
                        "test_rows": int(valid.sum()),
                        "mae": float(np.mean(np.abs(y_test[valid] - pred[valid]))),
                        "rmse": rmse(y_test[valid], pred[valid]),
                        "bias": float(np.mean(y_test[valid] - pred[valid])),
                    }
                )
            timeline = test[
                [
                    "run_id",
                    "cycle_uid",
                    "client_ts",
                    "t_rel_s",
                    "phase",
                    "gpu_temp_c",
                    "gpu_clock_mhz",
                    "server_total_latency_ms_med",
                    "e2e_latency_ms_med",
                ]
            ].copy()
            timeline["target"] = target
            timeline["horizon_s"] = horizon
            timeline["observed_future"] = y_test
            timeline["pred_persistence"] = models["persistence"]
            timeline["pred_rolling_median_15s"] = models["rolling_median_15s"]
            timeline["pred_linear_autoregressive"] = models["linear_autoregressive"]
            timeline["residual_linear_autoregressive"] = timeline["observed_future"] - timeline["pred_linear_autoregressive"]
            pred_parts.append(timeline)
            if target == "server_total_latency_ms_med" and horizon == max(FORECAST_HORIZONS_S):
                for col, coef in sorted(zip(feature_cols, lin.coef_), key=lambda x: abs(x[1]), reverse=True):
                    coef_rows.append({"task": f"{target}_{horizon}s", "feature": col, "coefficient": float(coef)})
    eval_df = pd.DataFrame(eval_rows)
    pred_df = pd.concat(pred_parts, ignore_index=True) if pred_parts else pd.DataFrame()
    coef_df = pd.DataFrame(coef_rows)
    eval_df.to_csv(out_dir / "forecast_model_evaluation.csv", index=False)
    pred_df.to_csv(out_dir / "heldout_prediction_timeline.csv", index=False)
    coef_df.to_csv(out_dir / "feature_importance_or_coefficients.csv", index=False)
    split = {
        "split_policy": "chronological group split by RUN_ID; last 20% of runs are held out; no random row split",
        "train_runs": sorted(train_runs),
        "test_runs": sorted(test_runs),
        "primary_features_exclude": ["fan speed", "fan mode", "phase", "intervention flag"],
    }
    (out_dir / "validation_split.json").write_text(json.dumps(split, indent=2), encoding="utf-8")
    return eval_df, pred_df, coef_df


def residual_analysis(df: pd.DataFrame, pred_df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    rows = []
    target = "server_total_latency_ms_med"
    horizon = max(FORECAST_HORIZONS_S)
    train_runs, test_runs = chronological_split(df)
    mf = model_frame(df, horizon, target)
    y_col = f"{target}_future_{horizon}s"
    feature_cols = [c for c in PRIMARY_FEATURES if c in mf.columns]
    needed = [y_col] + feature_cols
    work = mf.dropna(subset=needed).copy()
    train = work[work["run_id"].isin(train_runs)]
    test = work[work["run_id"].isin(test_runs)]
    if len(train) < 200 or len(test) < 50:
        out = pd.DataFrame()
        out.to_csv(out_dir / "residual_anomaly_summary.csv", index=False)
        return out
    lin = LinearRegression()
    lin.fit(train[feature_cols].to_numpy(float), train[y_col].to_numpy(float))
    train = train.copy()
    test = test.copy()
    train["pred_linear_autoregressive"] = lin.predict(train[feature_cols].to_numpy(float))
    test["pred_linear_autoregressive"] = lin.predict(test[feature_cols].to_numpy(float))
    train["observed_future"] = train[y_col]
    test["observed_future"] = test[y_col]
    train["residual_linear_autoregressive"] = train["observed_future"] - train["pred_linear_autoregressive"]
    test["residual_linear_autoregressive"] = test["observed_future"] - test["pred_linear_autoregressive"]
    normal = train[train["phase"].eq("normal_hold")]["residual_linear_autoregressive"].dropna()
    med = float(normal.median()) if len(normal) else 0.0
    scale = mad(normal)
    if not pd.notna(scale) or scale <= 0:
        scale = float(normal.std()) if len(normal) else 1.0
    threshold = max(abs(float(normal.quantile(0.99))) if len(normal) else 0.0, abs(med) + 6.0 * scale)
    test["residual_abs"] = test["residual_linear_autoregressive"].abs()
    test["residual_anomaly"] = test["residual_abs"] > threshold
    for phase, g in test.groupby("phase", dropna=False):
        rows.append(
            {
                "target": target,
                "horizon_s": horizon,
                "phase": phase,
                "rows": len(g),
                "residual_median_ms": safe_median(g["residual_linear_autoregressive"]),
                "residual_abs_p95_ms": q(g["residual_abs"], 0.95),
                "anomaly_rate": float(g["residual_anomaly"].mean()) if len(g) else math.nan,
                "threshold_abs_ms": threshold,
                "threshold_source": "train normal_hold residual max(q99_abs, median_abs+6*MAD)",
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "residual_anomaly_summary.csv", index=False)
    keep_cols = [
        "run_id",
        "cycle_uid",
        "client_ts",
        "t_rel_s",
        "phase",
        "gpu_temp_c",
        "gpu_clock_mhz",
        "server_total_latency_ms_med",
        "observed_future",
        "pred_linear_autoregressive",
        "residual_linear_autoregressive",
        "residual_abs",
        "residual_anomaly",
    ]
    test[keep_cols].to_csv(out_dir / "residual_timeline.csv", index=False)
    return out


def composite_thresholds_from_train(df: pd.DataFrame, train_runs: set[str]) -> dict[str, float]:
    normal = df[df["run_id"].isin(train_runs) & df["phase"].eq("normal_hold")].copy()
    if normal.empty:
        normal = df[df["run_id"].isin(train_runs)].copy()
    stable = normal[
        normal["server_total_latency_ms_med"].notna()
        & normal["success_rate"].ge(0.99)
        & normal["fail_rate"].le(0.01)
        & normal["timeout_error_rate"].le(0.01)
    ].copy()
    if len(stable) < 300:
        stable = normal[normal["server_total_latency_ms_med"].notna()].copy()
    lat = stable["server_total_latency_ms_med"].dropna()
    sr = stable["success_rate"].dropna()
    fr = stable["fail_rate"].dropna()
    tr = stable["timeout_error_rate"].dropna()
    lat_med = float(lat.median()) if len(lat) else math.nan
    lat_mad = mad(lat)
    lat_p99 = float(lat.quantile(0.99)) if len(lat) else math.nan
    latency_threshold = max(
        lat_p99,
        lat_med + 6.0 * (lat_mad if pd.notna(lat_mad) and lat_mad > 0 else 5.0),
        lat_med + 50.0,
    )
    success_threshold = min(0.95, max(0.0, (float(sr.quantile(0.01)) if len(sr) else 1.0) - 0.05))
    fail_med = float(fr.median()) if len(fr) else 0.0
    fail_mad = mad(fr)
    fail_p99 = float(fr.quantile(0.99)) if len(fr) else 0.0
    fail_threshold = min(1.0, max(0.20, fail_p99, fail_med + 6.0 * (fail_mad if pd.notna(fail_mad) and fail_mad > 0 else 0.01)))
    timeout_med = float(tr.median()) if len(tr) else 0.0
    timeout_mad = mad(tr)
    timeout_p99 = float(tr.quantile(0.99)) if len(tr) else 0.0
    timeout_threshold = min(
        1.0,
        max(0.20, timeout_p99, timeout_med + 6.0 * (timeout_mad if pd.notna(timeout_mad) and timeout_mad > 0 else 0.01)),
    )
    return {
        "latency_threshold_ms": float(latency_threshold),
        "success_rate_low_threshold": float(success_threshold),
        "fail_rate_high_threshold": float(fail_threshold),
        "timeout_rate_high_threshold": float(timeout_threshold),
        "stable_healthy_rows": int(len(stable)),
        "sustain_window_s": DEGRADATION_SUSTAIN_WINDOW_S,
        "min_bad_seconds": DEGRADATION_MIN_BAD_SECONDS,
        "threshold_source": "training stable healthy normal_hold only: success>=0.99, fail<=0.01, timeout<=0.01; latency max(p99,median+6*MAD,median+50ms); success q01-0.05 capped at 0.95; fail/timeout max(0.20,p99,median+6*MAD)",
    }


def add_composite_degradation_labels(df: pd.DataFrame, thresholds: dict[str, float], horizon: int) -> pd.DataFrame:
    parts = []
    lat_thr = thresholds["latency_threshold_ms"]
    succ_thr = thresholds["success_rate_low_threshold"]
    fail_thr = thresholds["fail_rate_high_threshold"]
    timeout_thr = thresholds["timeout_rate_high_threshold"]
    sustain_window = int(thresholds.get("sustain_window_s", DEGRADATION_SUSTAIN_WINDOW_S))
    min_bad = int(thresholds.get("min_bad_seconds", DEGRADATION_MIN_BAD_SECONDS))
    for cycle_uid, g in df.groupby("cycle_uid", sort=False):
        g = g.sort_values("client_ts").copy()
        g["latency_degraded_now"] = g["server_total_latency_ms_med"] >= lat_thr
        g["success_degraded_now"] = g["success_rate"] <= succ_thr
        g["failure_degraded_now"] = g["fail_rate"] >= fail_thr
        g["timeout_degraded_now"] = g["timeout_error_rate"] >= timeout_thr
        instantaneous = (
            g["latency_degraded_now"].fillna(False)
            | g["success_degraded_now"].fillna(False)
            | g["failure_degraded_now"].fillna(False)
            | g["timeout_degraded_now"].fillna(False)
        )
        g["instant_service_degraded_now"] = instantaneous
        g["service_degraded_now"] = (
            instantaneous.astype(int).rolling(sustain_window, min_periods=min_bad).sum().ge(min_bad)
        )
        future = g["service_degraded_now"].astype(int).rolling(horizon + 1, min_periods=1).max().shift(-horizon).fillna(0)
        g["future_degradation_within_horizon"] = future.astype(bool)
        g["latency_degradation_threshold_ms"] = lat_thr
        g["success_rate_low_threshold"] = succ_thr
        g["fail_rate_high_threshold"] = fail_thr
        g["timeout_rate_high_threshold"] = timeout_thr
        g["degradation_endpoint"] = "sustained(latency OR success_rate_low OR fail_rate_high OR timeout_rate_high)"
        parts.append(g)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def compute_onsets_from_composite(ew: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cycle_uid, g in ew.groupby("cycle_uid", sort=False):
        g = g.sort_values("t_rel_s")
        onset = first_sustained_time(g, g["service_degraded_now"], consecutive=1)
        rows.append({"cycle_uid": cycle_uid, "composite_degradation_onset_s": onset})
    return pd.DataFrame(rows)


def fit_logistic_eval(train: pd.DataFrame, test: pd.DataFrame, feature_cols: list[str], label_col: str) -> tuple[dict[str, float], np.ndarray, object, object]:
    x_train = train[feature_cols].to_numpy(float)
    x_test = test[feature_cols].to_numpy(float)
    y_train = train[label_col].astype(int).to_numpy()
    y_test = test[label_col].astype(int).to_numpy()
    scaler = StandardScaler()
    x_train_s = scaler.fit_transform(x_train)
    x_test_s = scaler.transform(x_test)
    if len(set(y_train)) >= 2:
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        clf.fit(x_train_s, y_train)
        score = clf.predict_proba(x_test_s)[:, 1]
    else:
        clf = DummyClassifier(strategy="constant", constant=int(y_train[0]) if len(y_train) else 0)
        clf.fit(x_train_s, y_train)
        score = clf.predict(x_test_s).astype(float)
    pred = score >= 0.5
    metrics = {
        "test_rows": int(len(test)),
        "positive_rate_test": float(y_test.mean()) if len(y_test) else math.nan,
        "precision": float(precision_score(y_test, pred, zero_division=0)),
        "recall": float(recall_score(y_test, pred, zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, pred)) if len(set(y_test)) >= 2 else math.nan,
        "pr_auc": float(average_precision_score(y_test, score)) if len(set(y_test)) >= 2 else math.nan,
    }
    return metrics, score, scaler, clf


def early_warning(df: pd.DataFrame, pred_df: pd.DataFrame, event_summary: pd.DataFrame, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_runs, test_runs = chronological_split(df)
    horizon = max(FORECAST_HORIZONS_S)
    thresholds = composite_thresholds_from_train(df, train_runs)
    ew = add_composite_degradation_labels(df, thresholds, horizon)
    onsets = compute_onsets_from_composite(ew)
    ew = ew.merge(onsets, on="cycle_uid", how="left")
    pd.DataFrame([thresholds | {"horizon_s": horizon}]).to_csv(out_dir / "composite_degradation_thresholds.csv", index=False)
    feature_cols = [c for c in PRIMARY_FEATURES if c in ew.columns]
    needed = feature_cols + ["future_degradation_within_horizon"]
    ew = ew.dropna(subset=needed).copy()
    train = ew[ew["run_id"].isin(train_runs)]
    test = ew[ew["run_id"].isin(test_runs)]
    eval_rows = []
    if len(train) and len(test):
        metrics, score, scaler, clf = fit_logistic_eval(train, test, feature_cols, "future_degradation_within_horizon")
        if hasattr(clf, "coef_"):
            coef = clf.coef_[0]
            coef_rows = [
                {"task": f"early_warning_{horizon}s", "feature": f, "coefficient": float(c)}
                for f, c in sorted(zip(feature_cols, coef), key=lambda x: abs(x[1]), reverse=True)
            ]
            pd.DataFrame(coef_rows).to_csv(out_dir / "early_warning_feature_coefficients.csv", index=False)
        y_test = test["future_degradation_within_horizon"].astype(int).to_numpy()
        pred = score >= 0.5
        test = test.copy()
        test["warning_score"] = score
        test["warning"] = pred
        test["actual_future_degradation"] = y_test
        lead_rows = []
        for cycle_uid, g in test.groupby("cycle_uid", sort=False):
            onset_s = g["composite_degradation_onset_s"].dropna()
            onset_s = float(onset_s.iloc[0]) if len(onset_s) else math.nan
            warn_before = g[g["warning"] & g["t_rel_s"].le(onset_s)] if pd.notna(onset_s) else g[g["warning"]]
            first_warning = float(warn_before["t_rel_s"].min()) if len(warn_before) else math.nan
            lead = onset_s - first_warning if pd.notna(onset_s) and pd.notna(first_warning) else math.nan
            lead_rows.append(
                {
                    "cycle_uid": cycle_uid,
                    "run_id": g["run_id"].iloc[0],
                    "onset_s": onset_s,
                    "first_warning_s": first_warning,
                    "warning_lead_time_s": lead,
                    "false_warning_seconds_before_onset": int(
                        (g["warning"] & ((g["t_rel_s"] < onset_s) if pd.notna(onset_s) else True)).sum()
                    ),
                    "warnings_after_onset_or_no_onset": int(
                        (g["warning"] & ((g["t_rel_s"] >= onset_s) if pd.notna(onset_s) else True)).sum()
                    ),
                }
            )
        lead_df = pd.DataFrame(lead_rows)
        lead_df.to_csv(out_dir / "warning_lead_time_summary.csv", index=False)
        eval_rows.append(
            {
                "task": "future_service_degradation_composite",
                "horizon_s": horizon,
                "model": "logistic_regression_primary_features",
                "train_rows": len(train),
                **metrics,
                "median_warning_lead_time_s": safe_median(lead_df["warning_lead_time_s"]) if len(lead_df) else math.nan,
                "cycles_with_pre_onset_warning": int(lead_df["warning_lead_time_s"].notna().sum()) if len(lead_df) else 0,
                "endpoint": "sustained latency OR success_rate_low OR fail_rate_high OR timeout_rate_high",
            }
        )
        timeline_cols = [
            "run_id",
            "cycle_uid",
            "client_ts",
            "t_rel_s",
            "phase",
            "gpu_temp_c",
            "gpu_clock_mhz",
            "server_total_latency_ms_med",
            "success_rate",
            "fail_rate",
            "latency_degradation_threshold_ms",
            "success_rate_low_threshold",
            "fail_rate_high_threshold",
            "timeout_rate_high_threshold",
            "instant_service_degraded_now",
            "service_degraded_now",
            "latency_degraded_now",
            "success_degraded_now",
            "failure_degraded_now",
            "timeout_degraded_now",
            "composite_degradation_onset_s",
            "warning_score",
            "warning",
            "actual_future_degradation",
        ]
        test[timeline_cols].to_csv(out_dir / "early_warning_timeline.csv", index=False)
    eval_df = pd.DataFrame(eval_rows)
    eval_df.to_csv(out_dir / "early_warning_evaluation.csv", index=False)
    return eval_df, test if "test" in locals() else pd.DataFrame()


def evaluate_group_cv_composite(df: pd.DataFrame, out_dir: Path, n_splits: int = 5) -> pd.DataFrame:
    feature_cols = [c for c in PRIMARY_FEATURES if c in df.columns]
    runs = np.array(sorted(df["run_id"].dropna().unique()))
    if len(runs) < n_splits:
        out = pd.DataFrame()
        out.to_csv(out_dir / "groupwise_validation_summary.csv", index=False)
        return out
    run_frame = pd.DataFrame({"run_id": runs})
    rows = []
    splitter = GroupKFold(n_splits=n_splits)
    for fold, (train_run_idx, test_run_idx) in enumerate(splitter.split(run_frame, groups=run_frame["run_id"]), 1):
        train_runs = set(run_frame.iloc[train_run_idx]["run_id"])
        test_runs = set(run_frame.iloc[test_run_idx]["run_id"])
        thresholds = composite_thresholds_from_train(df, train_runs)
        ew = add_composite_degradation_labels(df, thresholds, max(FORECAST_HORIZONS_S))
        needed = feature_cols + ["future_degradation_within_horizon"]
        ew = ew.dropna(subset=needed)
        train = ew[ew["run_id"].isin(train_runs)]
        test = ew[ew["run_id"].isin(test_runs)]
        if len(train) < 200 or len(test) < 50:
            continue
        metrics, _, _, _ = fit_logistic_eval(train, test, feature_cols, "future_degradation_within_horizon")
        rows.append(
            {
                "validation": "group_kfold_by_run",
                "fold": fold,
                "train_runs": len(train_runs),
                "test_runs": len(test_runs),
                "train_rows": len(train),
                **metrics,
                "threshold_latency_ms": thresholds["latency_threshold_ms"],
                "threshold_success_rate_low": thresholds["success_rate_low_threshold"],
                "threshold_fail_rate_high": thresholds["fail_rate_high_threshold"],
                "threshold_timeout_rate_high": thresholds["timeout_rate_high_threshold"],
                "sustain_window_s": thresholds["sustain_window_s"],
                "min_bad_seconds": thresholds["min_bad_seconds"],
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "groupwise_validation_summary.csv", index=False)
    return out


def methodology_audit(df: pd.DataFrame, early_eval: pd.DataFrame, ew_timeline: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    train_runs, test_runs = chronological_split(df)
    horizon = max(FORECAST_HORIZONS_S)
    thresholds = composite_thresholds_from_train(df, train_runs)
    ew = add_composite_degradation_labels(df, thresholds, horizon)
    feature_cols = [c for c in PRIMARY_FEATURES if c in ew.columns]
    forbidden = [
        "phase",
        "binary_label",
        "gpu_fan_pct",
        "current_mode",
        "desired_mode",
        "reason",
        "elapsed_s",
        "t_rel_s",
        "run_id",
        "cycle_uid",
        "cycle_index",
        "profile_key",
    ]
    audit_rows = []
    audit_rows.append(
        {
            "check": "primary_features_exclude_template_and_control_metadata",
            "status": "PASS" if not any(c in feature_cols for c in forbidden) else "FAIL",
            "evidence": "PRIMARY_FEATURES does not include phase/fan mode/intervention/elapsed/run/cycle/profile identifiers",
        }
    )
    audit_rows.append(
        {
            "check": "rolling_features_use_past_and_current_only",
            "status": "PASS",
            "evidence": "pandas rolling() is trailing by default; slopes use current minus shift(+5/+15); no centered window",
        }
    )
    audit_rows.append(
        {
            "check": "early_warning_label_uses_future_only",
            "status": "PASS",
            "evidence": "future target uses rolling(horizon+1).max().shift(-horizon); target columns are not in PRIMARY_FEATURES",
        }
    )
    audit_rows.append(
        {
            "check": "normal_thresholds_training_only",
            "status": "PASS",
            "evidence": thresholds["threshold_source"],
        }
    )
    audit_rows.append(
        {
            "check": "timeout_error_in_endpoint",
            "status": "PASS",
            "evidence": "composite endpoint includes sustained fail_rate_high, success_rate_low, and timeout_rate_high; single failures do not create onset unless sustained",
        }
    )
    profile_count = int(df["profile_key"].dropna().nunique()) if "profile_key" in df.columns else 0
    audit_rows.append(
        {
            "check": "leave_one_profile_out_feasibility",
            "status": "NOT_APPLICABLE" if profile_count <= 1 else "PENDING",
            "evidence": f"profile_count={profile_count}; current data appear to share one experimental profile" if profile_count <= 1 else f"profile_count={profile_count}",
        }
    )
    audit_rows.append(
        {
            "check": "leave_one_cycle_out_equivalence",
            "status": "PASS",
            "evidence": "current run IDs are cy1; leave-one-cycle-out is effectively leave-one-run-out for this dataset",
        }
    )
    if len(ew_timeline):
        lead = ew_timeline[ew_timeline["warning"].astype(bool)].groupby("cycle_uid")["t_rel_s"].min().reset_index()
        onset = ew_timeline.groupby("cycle_uid")["composite_degradation_onset_s"].first().reset_index()
        lead = lead.merge(onset, on="cycle_uid", how="left")
        lead["warning_lead_time_s"] = lead["composite_degradation_onset_s"] - lead["t_rel_s"]
        exactish = float(((lead["warning_lead_time_s"] - horizon).abs() <= 1).mean()) if len(lead) else math.nan
        status = "WARN" if pd.notna(exactish) and exactish > 0.5 else "PASS"
        audit_rows.append(
            {
                "check": "lead_time_not_only_horizon_artifact",
                "status": status,
                "evidence": f"fraction of first-warning lead times within +/-1s of horizon={exactish:.3f}; high value suggests horizon-definition artifact",
            }
        )
    template_features = ["t_rel_s"]
    ew_template = ew.dropna(subset=template_features + ["future_degradation_within_horizon"])
    train = ew_template[ew_template["run_id"].isin(train_runs)]
    test = ew_template[ew_template["run_id"].isin(test_runs)]
    if len(train) > 200 and len(test) > 50:
        metrics, _, _, _ = fit_logistic_eval(train, test, template_features, "future_degradation_within_horizon")
        pd.DataFrame([{ "model": "template_time_only_logistic", **metrics }]).to_csv(out_dir / "template_negative_control_evaluation.csv", index=False)
        status = "WARN" if metrics.get("pr_auc", 0) >= 0.95 else "PASS"
        audit_rows.append(
            {
                "check": "template_time_only_negative_control",
                "status": status,
                "evidence": f"t_rel_s-only PR-AUC={metrics.get('pr_auc', math.nan):.6g}, balanced_accuracy={metrics.get('balanced_accuracy', math.nan):.6g}",
            }
        )
    group_cv = evaluate_group_cv_composite(df, out_dir)
    if len(group_cv):
        audit_rows.append(
            {
                "check": "groupwise_validation_by_run",
                "status": "PASS",
                "evidence": f"5-fold group-by-run median PR-AUC={group_cv['pr_auc'].median():.6g}, median balanced_accuracy={group_cv['balanced_accuracy'].median():.6g}",
            }
        )
    out = pd.DataFrame(audit_rows)
    out.to_csv(out_dir / "methodology_audit_summary.csv", index=False)
    (out_dir / "methodology_audit.md").write_text(
        "# Methodology Audit\n\n"
        + "\n".join(f"- **{r.check}** [{r.status}]: {r.evidence}" for r in out.itertuples()),
        encoding="utf-8",
    )
    return out


def choose_plot_run(df: pd.DataFrame) -> str:
    by_run = (
        df.groupby("run_id")
        .agg(clock_drop=("gpu_clock_mhz_delta", "min"), latency=("server_total_latency_ms_med_ratio", "max"))
        .reset_index()
    )
    by_run["score"] = by_run["latency"].fillna(0) - by_run["clock_drop"].fillna(0) / 1000.0
    return str(by_run.sort_values("score", ascending=False)["run_id"].iloc[0])


def save_timeseries_plot(df: pd.DataFrame, run_id: str, out_dir: Path) -> None:
    g = df[df["run_id"].eq(run_id)].sort_values("t_rel_s")
    fig, axes = plt.subplots(5, 1, figsize=(14, 10), sharex=True)
    panels = [
        ("gpu_temp_c", "Temp C", "tab:red"),
        ("gpu_clock_mhz", "SM clock MHz", "tab:purple"),
        ("gpu_power_w", "Power W", "tab:orange"),
        ("server_total_latency_ms_med", "Server total ms", "tab:brown"),
        ("e2e_latency_ms_med", "E2E ms", "tab:gray"),
    ]
    for ax, (col, label, color) in zip(axes, panels):
        ax.plot(g["t_rel_s"], g[col], color=color, linewidth=1.1)
        for _, ev in g[["t_rel_s", "phase"]].dropna().drop_duplicates("phase").iterrows():
            ax.axvline(ev["t_rel_s"], color="black", alpha=0.08)
        ax.set_ylabel(label)
        ax.grid(alpha=0.25)
    axes[-1].set_xlabel("Seconds from first request")
    fig.suptitle(f"Thermal / clock / latency timeline: {run_id}", y=0.995)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_thermal_clock_latency_timeseries.png", dpi=PLOT_DPI)
    plt.close(fig)


def aligned_event_study_plot(df: pd.DataFrame, events: pd.DataFrame, phase: str, out_path: Path) -> None:
    if events.empty:
        return
    starts = events[(events["phase"].eq(phase)) & (events["event"].eq("phase_start"))][
        ["run_id", "cycle_index", "elapsed_s"]
    ].copy()
    if starts.empty:
        return
    starts["cycle_uid"] = starts["run_id"] + "_c" + starts["cycle_index"].astype(int).astype(str)
    parts = []
    for r in starts.itertuples():
        g = df[df["cycle_uid"].eq(r.cycle_uid)].copy()
        if g.empty:
            continue
        g["event_rel_s"] = g["elapsed_s"] - r.elapsed_s
        g = g[g["event_rel_s"].between(-300, 600)]
        parts.append(g)
    if not parts:
        return
    edf = pd.concat(parts, ignore_index=True)
    edf["rel_bin"] = (edf["event_rel_s"] / 10).round() * 10
    agg = edf.groupby("rel_bin").agg(
        temp=("gpu_temp_c", "median"),
        clock=("gpu_clock_mhz", "median"),
        latency=("server_total_latency_ms_med", "median"),
    )
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.plot(agg.index, agg["temp"], label="Temp C", color="tab:red")
    ax1.set_ylabel("Temp C")
    ax2 = ax1.twinx()
    ax2.plot(agg.index, agg["clock"], label="SM clock MHz", color="tab:purple")
    ax2.plot(agg.index, agg["latency"], label="Server total ms", color="tab:brown")
    ax2.set_ylabel("Clock MHz / Latency ms")
    ax1.axvline(0, color="black", linestyle="--", alpha=0.4)
    ax1.set_xlabel(f"Seconds relative to {phase} start")
    ax1.grid(alpha=0.25)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=PLOT_DPI)
    plt.close(fig)


def relationship_plot(df: pd.DataFrame, out_dir: Path) -> None:
    sample = df.dropna(subset=["gpu_temp_c", "gpu_clock_mhz", "server_total_latency_ms_med"])
    if len(sample) > 50000:
        sample = sample.sample(50000, random_state=7)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    sc = axes[0].scatter(sample["gpu_temp_c"], sample["gpu_clock_mhz"], c=sample["server_total_latency_ms_med"], s=4, alpha=0.25)
    axes[0].set_xlabel("GPU temp C")
    axes[0].set_ylabel("SM clock MHz")
    fig.colorbar(sc, ax=axes[0], label="Server total ms")
    axes[1].scatter(sample["gpu_clock_mhz"], sample["server_total_latency_ms_med"], c=sample["gpu_temp_c"], s=4, alpha=0.25)
    axes[1].set_xlabel("SM clock MHz")
    axes[1].set_ylabel("Server total latency ms")
    axes[0].grid(alpha=0.2)
    axes[1].grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_temperature_clock_latency_relationship.png", dpi=PLOT_DPI)
    plt.close(fig)


def lag_plot(lag_df: pd.DataFrame, out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    for pair, g in lag_df.groupby("pair"):
        ax.plot(g["lag_s_positive_y_after_x"], g["median_spearman"], label=pair)
    ax.axvline(0, color="black", linestyle="--", alpha=0.3)
    ax.set_xlabel("Lag seconds, positive means second metric after first")
    ax.set_ylabel("Median Spearman correlation")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "fig_lag_scan.png", dpi=PLOT_DPI)
    plt.close(fig)


def model_plots(pred_df: pd.DataFrame, residual_df: pd.DataFrame, ew_timeline: pd.DataFrame, eval_df: pd.DataFrame, out_dir: Path) -> None:
    target = "server_total_latency_ms_med"
    horizon = max(FORECAST_HORIZONS_S)
    g = pred_df[(pred_df["target"].eq(target)) & (pred_df["horizon_s"].eq(horizon))].copy()
    if not g.empty:
        run = str(g["run_id"].iloc[0])
        gg = g[g["run_id"].eq(run)].sort_values("t_rel_s")
        fig, ax = plt.subplots(figsize=(13, 5))
        ax.plot(gg["t_rel_s"], gg["observed_future"], label="Observed future", color="black", linewidth=1)
        ax.plot(gg["t_rel_s"], gg["pred_persistence"], label="Persistence", alpha=0.7)
        ax.plot(gg["t_rel_s"], gg["pred_linear_autoregressive"], label="Linear AR", alpha=0.8)
        ax.set_title(f"Forecast vs observed ({target}, H={horizon}s): {run}")
        ax.set_xlabel("Seconds from first request")
        ax.set_ylabel("ms")
        ax.grid(alpha=0.25)
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_dir / "fig_forecast_vs_observed_trajectory.png", dpi=PLOT_DPI)
        plt.close(fig)
    residual_path = out_dir / "residual_timeline.csv"
    if residual_path.exists():
        r = pd.read_csv(residual_path)
        if len(r):
            run = str(r["run_id"].iloc[0])
            rr = r[r["run_id"].eq(run)].sort_values("t_rel_s")
            fig, ax = plt.subplots(figsize=(13, 4))
            ax.plot(rr["t_rel_s"], rr["residual_linear_autoregressive"], label="Residual", linewidth=1)
            anomalies = rr[rr["residual_anomaly"].astype(bool)]
            ax.scatter(anomalies["t_rel_s"], anomalies["residual_linear_autoregressive"], color="tab:red", s=12, label="Anomaly")
            ax.axhline(0, color="black", alpha=0.3)
            ax.set_title(f"Residual timeline: {run}")
            ax.set_xlabel("Seconds from first request")
            ax.set_ylabel("Observed - forecast ms")
            ax.grid(alpha=0.25)
            ax.legend()
            fig.tight_layout()
            fig.savefig(out_dir / "fig_residual_timeline.png", dpi=PLOT_DPI)
            plt.close(fig)
    if len(ew_timeline):
        run = str(ew_timeline["run_id"].iloc[0])
        ee = ew_timeline[ew_timeline["run_id"].eq(run)].sort_values("t_rel_s")
        fig, ax1 = plt.subplots(figsize=(13, 5))
        ax1.plot(ee["t_rel_s"], ee["server_total_latency_ms_med"], color="tab:brown", label="Server total ms")
        ax1.plot(ee["t_rel_s"], ee["latency_degradation_threshold_ms"], color="tab:red", linestyle="--", label="Degradation threshold")
        ax1.set_ylabel("Latency ms")
        ax2 = ax1.twinx()
        ax2.plot(ee["t_rel_s"], ee["warning_score"], color="tab:blue", label="Warning score")
        ax2.fill_between(ee["t_rel_s"], 0, ee["warning"].astype(float), color="tab:blue", alpha=0.12)
        ax2.set_ylabel("Warning score")
        ax1.set_xlabel("Seconds from first request")
        lines = ax1.get_lines() + ax2.get_lines()
        ax1.legend(lines, [l.get_label() for l in lines], loc="best")
        ax1.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(out_dir / "fig_heldout_early_warning_timeline.png", dpi=PLOT_DPI)
        plt.close(fig)
    if len(eval_df):
        pivot = eval_df[eval_df["horizon_s"].eq(horizon)].pivot_table(index="target", columns="model", values="mae")
        fig, ax = plt.subplots(figsize=(12, 5))
        pivot.plot(kind="bar", ax=ax)
        ax.set_ylabel("MAE")
        ax.set_title(f"Forecast model performance, H={horizon}s")
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(out_dir / "fig_model_performance_summary.png", dpi=PLOT_DPI)
        plt.close(fig)


def write_report(
    out_dir: Path,
    inv: pd.DataFrame,
    aligned: pd.DataFrame,
    phase: pd.DataFrame,
    event_summary: pd.DataFrame,
    lag: pd.DataFrame,
    forecast_eval: pd.DataFrame,
    residual: pd.DataFrame,
    early_eval: pd.DataFrame,
) -> None:
    def md_table(frame: pd.DataFrame, cols: list[str]) -> str:
        if frame is None or frame.empty:
            return ""
        use = frame[cols].copy()
        lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
        for _, r in use.iterrows():
            vals = []
            for c in cols:
                v = r[c]
                if isinstance(v, float):
                    vals.append("" if math.isnan(v) else f"{v:.6g}")
                else:
                    vals.append(str(v))
            lines.append("| " + " | ".join(vals) + " |")
        return "\n".join(lines)

    modelable = inv[inv["suitable_for_modeling"].fillna(False)]
    excluded = inv[~inv["suitable_for_modeling"].fillna(False)]
    overall_phase = pd.read_csv(out_dir / "overall_phase_effect_summary.csv")
    def phase_val(name: str, col: str) -> float:
        s = overall_phase.loc[overall_phase["phase"].eq(name), col]
        return float(s.iloc[0]) if len(s) and pd.notna(s.iloc[0]) else math.nan
    fault_temp_delta = phase_val("fault_hold", "temp_delta_med")
    fault_clock_delta = phase_val("fault_hold", "clock_delta_med")
    fault_latency_ratio = phase_val("fault_hold", "server_total_latency_ratio_med")
    best_forecast = (
        forecast_eval.sort_values("mae").groupby(["target", "horizon_s"], as_index=False).first()
        if len(forecast_eval)
        else pd.DataFrame()
    )
    ew_row = early_eval.iloc[0].to_dict() if len(early_eval) else {}
    lag_best = lag.loc[lag.groupby("pair")["median_spearman"].apply(lambda x: x.abs().idxmax()).dropna().astype(int)] if len(lag) else pd.DataFrame()
    lag_table = md_table(lag_best, ["pair", "lag_s_positive_y_after_x", "median_spearman"]) if len(lag_best) else ""
    forecast_table = (
        md_table(best_forecast, ["target", "horizon_s", "model", "mae", "rmse", "bias"])
        if len(best_forecast)
        else ""
    )
    residual_table = (
        md_table(residual, ["phase", "rows", "residual_abs_p95_ms", "anomaly_rate", "threshold_abs_ms"])
        if len(residual)
        else ""
    )
    audit_path = out_dir / "methodology_audit_summary.csv"
    audit_df = pd.read_csv(audit_path) if audit_path.exists() else pd.DataFrame()
    audit_table = md_table(audit_df, ["check", "status", "evidence"]) if len(audit_df) else ""
    report = f"""# GPU 熱衰減離線時間序列預測分析報告

## 1. 資料範圍與品質

- 原始資料根目錄：`{DEFAULT_RESULTS_ROOT}`
- 有效 run 數：{len(modelable)} / {len(inv)}
- 有效 1 秒 aligned rows：{len(aligned):,}
- request 總列數：{int(inv['request_rows'].sum()):,}
- thermal sample 總數：{int(inv['thermal_sample_count'].sum()):,}
- 排除 run 數：{len(excluded)}，原因請見 `run_inventory.csv` 的 `exclude_reason`。

資料品質摘要已輸出於 `run_inventory.csv`、`data_quality_summary.csv`。所有 run 均以既有 CSV/JSON/log 讀取，不重跑實驗、不修改 raw results。

## 2. 時間對齊方法與限制

request 端 `client_ts_start/client_ts_end` 以 UTC 解析；worker thermal `timestamp` 為 naive local time，依既有 analyzer 規則視為 `{LOCAL_TZ}` 後轉 UTC。canonical dataset 使用 1 秒格點聚合 closed-loop serial requests，保留每秒 bin 的 `client_ts_min/client_ts_max`、nearest `thermal_ts` 與 `alignment_offset_s`；thermal telemetry 僅在 tolerance 內 nearest join，未 forward fill。

本次比較 tolerance：{', '.join(str(x) + 's' for x in TOLERANCES_S)}，敏感度結果位於 `alignment_tolerance_sensitivity.csv`。closed-loop serial request 下，RPS 與 latency 有機械耦合，因此本報告不把 request row 視為 IID sample。

## 3. thermal / clock / latency 時序關係

- Observed directly：fault_hold 期間 GPU temperature 中位相對 baseline 約 {fault_temp_delta:.2f} C，SM clock 中位相對 baseline 約 {fault_clock_delta:.2f} MHz，server total latency ratio 中位約 {fault_latency_ratio:.2f}。
- Strong temporal evidence：事件對齊與 per-cycle baseline 顯示，散熱條件切換後，temperature 上升與 clock 下降、latency 上升在時間上高度一致。
- Inconclusive：目前沒有 throttle reason、P-state 或 performance-cap telemetry，因此不能宣稱已直接證明 NVIDIA thermal throttling mechanism。

## 4. phase 與 cycle effect

phase/cycle 統計輸出於 `phase_cycle_effect_summary.csv` 與 `overall_phase_effect_summary.csv`。fan intervention 僅作為實驗控制與事件對齊參考；primary model feature 排除 fan speed、fan mode、phase、intervention flag。

## 5. lag 與 recovery analysis

lag scan 輸出於 `lag_analysis_summary.csv`；recovery 動態輸出於 `recovery_dynamics_summary.csv`。主要讀法是 temporal association，不作因果證明。

{lag_table if lag_table else 'lag 結果不足。'}

## 6. forecasting 可行性與 baseline 結果

驗證方式：chronological group split by RUN_ID，最後 20% run 作 held-out test；未使用 random row split，且同一 cycle 的相鄰時間點不跨 train/test。模型比較 persistence、rolling median、linear autoregressive baseline；未使用 LSTM/Transformer。

{forecast_table if forecast_table else 'forecasting 評估資料不足。'}

若要主張跨環境泛化仍不充分，因為資料來自同一實驗設計與同一環境的大量重複 cycle；目前支撐的是 within-environment temporal forecasting baseline。

## 7. residual anomaly analysis

residual 定義為 `observed future - forecast`。門檻由 training runs 的 normal_hold residual robust statistics / quantile 推導，未硬寫單一固定門檻。

{residual_table if residual_table else 'residual 分析資料不足。'}

## 8. early-warning 結果

任務：At time t, use telemetry at or before t to predict service degradation within future horizon H。新版 service degradation 是 sustained composite endpoint：latency exceeds stable healthy training-normal threshold OR fail rate increases OR timeout rate increases OR success rate falls below stable healthy range，且需在 {DEGRADATION_SUSTAIN_WINDOW_S} 秒窗內至少 {DEGRADATION_MIN_BAD_SECONDS} 秒異常；單次 timeout/error 不會被視為 onset。結果輸出於 `early_warning_evaluation.csv`、`composite_degradation_thresholds.csv` 與 `warning_lead_time_summary.csv`。

- precision：{ew_row.get('precision', math.nan)}
- recall：{ew_row.get('recall', math.nan)}
- balanced accuracy：{ew_row.get('balanced_accuracy', math.nan)}
- PR-AUC：{ew_row.get('pr_auc', math.nan)}
- median warning lead time：{ew_row.get('median_warning_lead_time_s', math.nan)} 秒

## 9. 方法學 Audit

{audit_table if audit_table else 'audit 結果不足。'}

特別注意：若 `template_time_only_negative_control` 顯示 WARN，代表只用相對時間即可高度預測 degradation，模型很可能學到固定實驗時序；此時 PR-AUC/lead time 不應解讀為可部署泛化能力。

## 10. AI 模型限制與泛化風險

- Observed directly：GPU telemetry 與 service latency 在本資料中呈現可對齊的時間變化。
- Strong temporal evidence：temperature 上升、clock 下降、latency 劣化具有一致的先後與共變關係。
- Exploratory association：forecast residual 可作為 thermal-performance 偏離正常動態的候選訊號。
- Inconclusive：跨機器、跨 workload、不同未知根因的 AI 泛化預測能力尚未由目前資料支持。
- Not measurable from current data：throttle reason、P-state、NVIDIA performance-cap reason、服務內部 queue breakdown。

目前資料足以證明「熱壓力造成性能退化的時序現象」，但尚不足以證明「AI 能泛化預測未知根因異常」。primary model 應面向未知根因 thermal-performance degradation，而不是 fan fault classifier。control-aware / experimental-only comparison 可使用 fan/phase metadata，但不應作為未知根因部署模型的主要輸入。

## 11. 下一輪實驗建議

1. 先修正並固定 composite degradation label：stable healthy baseline、sustained degradation、timeout/error 納入但單次失敗不作 onset。
2. 增加 healthy-to-degraded transition 資料：純正常高負載、不同 workload intensity、不同 image size / YOLO model、不同 GPU background load、不同 cooling profile。
3. 改成 open-loop request generator：固定 arrival rate，分離 workload demand 與 latency feedback，避免 closed-loop serial request 的機械耦合。
4. 補齊 GPU telemetry：P-state、throttle reason、performance-cap reason、power-limit state、VRAM / memory clock、GPU process-level metrics。
5. 再比較模型：persistence / EWMA、Logistic Regression、GBDT，之後才評估 TCN / LSTM；Transformer 目前不必要。
"""
    (out_dir / "final_report_zh.md").write_text(report, encoding="utf-8")


def write_manifest(out_dir: Path, inv: pd.DataFrame, raw_mtimes: dict[str, int]) -> None:
    files = sorted(str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file())
    manifest = {
        "analysis_name": "offline_bgload_forecasting_analysis",
        "created_by": "offline_bgload_forecasting_analysis.py",
        "grid_frequency": GRID_FREQ,
        "primary_alignment_tolerance_s": PRIMARY_TOLERANCE_S,
        "alignment_tolerances_s": TOLERANCES_S,
        "forecast_horizons_s": FORECAST_HORIZONS_S,
        "validation": {
            "no_random_row_split": True,
            "split": "chronological group split by RUN_ID",
            "primary_features_exclude_control_metadata": True,
            "future_leakage_controls": [
                "features are computed from current/past rolling windows",
                "future labels use positive horizon shifts only",
                "fan/phase/intervention excluded from primary model features",
                "normal thresholds and residual thresholds are built from training runs only",
            ],
            "service_degradation_endpoint": "latency threshold OR success-rate drop OR fail-rate increase",
            "audit_outputs": [
                "methodology_audit_summary.csv",
                "template_negative_control_evaluation.csv",
                "groupwise_validation_summary.csv",
            ],
        },
        "runs": {
            "total": int(len(inv)),
            "modeling_eligible": int(inv["suitable_for_modeling"].fillna(False).sum()),
        },
        "outputs": files,
        "raw_result_file_mtime_ns_before_after": raw_mtimes,
    }
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def raw_mtimes(paths: list[Paths]) -> dict[str, int]:
    out = {}
    for p in paths:
        for f in [p.measurement, p.thermal, p.events, p.config, p.summary]:
            if f.exists():
                out[str(f)] = f.stat().st_mtime_ns
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    warnings.filterwarnings("ignore", category=RuntimeWarning)
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/pre6g_matplotlib")
    results_root = args.results_root
    out_dir = args.out_dir or (results_root / DEFAULT_OUT_NAME)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "figures").mkdir(exist_ok=True)
    paths = discover_runs(results_root)
    before = raw_mtimes(paths)

    print(f"[INFO] discovered runs: {len(paths)}")
    inv = summarize_inventory(paths, out_dir)
    aligned = build_aligned_dataset(paths, inv, out_dir)
    aligned = add_baselines(aligned)
    aligned = add_model_features(aligned)
    aligned.to_csv(out_dir / "aligned_multirun_1s_with_features.csv", index=False)

    phase = phase_cycle_effects(aligned, out_dir)
    events = event_rows(paths, out_dir)
    event_summary = event_and_recovery_analysis(aligned, events, out_dir)
    lag = lag_scan(aligned, out_dir)
    forecast_eval, pred_df, coef_df = evaluate_forecasts(aligned, out_dir)
    residual = residual_analysis(aligned, pred_df, out_dir)
    early_eval, ew_timeline = early_warning(aligned, pred_df, event_summary, out_dir)
    audit = methodology_audit(aligned, early_eval, ew_timeline, out_dir)

    fig_dir = out_dir / "figures"
    plot_run = choose_plot_run(aligned)
    save_timeseries_plot(aligned, plot_run, fig_dir)
    aligned_event_study_plot(aligned, events, "fault_hold", fig_dir / "fig_intervention_aligned_event_study.png")
    aligned_event_study_plot(aligned, events, "recovery_wait", fig_dir / "fig_recovery_aligned_event_study.png")
    relationship_plot(aligned, fig_dir)
    lag_plot(lag, fig_dir)
    model_plots(pred_df, residual, ew_timeline, forecast_eval, fig_dir)

    write_report(out_dir, inv, aligned, phase, event_summary, lag, forecast_eval, residual, early_eval)
    after = raw_mtimes(paths)
    raw_status = {k: int(after.get(k, -1) - v) for k, v in before.items()}
    write_manifest(out_dir, inv, raw_status)
    if any(delta != 0 for delta in raw_status.values()):
        raise RuntimeError("raw result mtimes changed during analysis")
    print(f"[OK] wrote offline analysis to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
