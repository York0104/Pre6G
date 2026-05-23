#!/usr/bin/env python3
import sys
from pathlib import Path

import pandas as pd


def load_measurement(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["client_ts_start"] = pd.to_datetime(df["client_ts_start"], utc=True, errors="coerce")
    df["client_ts_end"] = pd.to_datetime(df["client_ts_end"], utc=True, errors="coerce")
    for col in [
        "e2e_latency_ms",
        "server_latency_ms",
        "server_total_latency_ms",
        "inter_request_gap_ms",
        "loop_elapsed_ms",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["client_ts_start"]).sort_values("client_ts_start").reset_index(drop=True)


def load_thermal(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    if getattr(ts.dt, "tz", None) is None:
        df["thermal_ts"] = ts.dt.tz_localize("Asia/Taipei").dt.tz_convert("UTC")
    else:
        df["thermal_ts"] = ts.dt.tz_convert("UTC")
    for col in [
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
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["thermal_ts"]).sort_values("thermal_ts").reset_index(drop=True)


def summarize_series(s: pd.Series, prefix: str, row: dict):
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return
    row[f"{prefix}_mean"] = round(s.mean(), 3)
    row[f"{prefix}_p50"] = round(s.quantile(0.5), 3)
    row[f"{prefix}_p95"] = round(s.quantile(0.95), 3)
    row[f"{prefix}_p99"] = round(s.quantile(0.99), 3)
    row[f"{prefix}_max"] = round(s.max(), 3)


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 analyze_single_pod_bgload_fan_cycle.py <RUN_DIR>")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    meas_path = run_dir / "measurement_raw.csv"
    thermal_path = run_dir / "thermal_cycle" / "worker_logs" / "thermal.csv"
    aligned_csv = run_dir / "aligned_serial_thermal.csv"
    per_cycle_csv = run_dir / "cycle_phase_summary.csv"
    overall_csv = run_dir / "overall_phase_summary.csv"
    out_txt = run_dir / "bgload_cycle_analysis.txt"

    meas = load_measurement(meas_path)
    thermal = load_thermal(thermal_path)
    meas["success_bool"] = meas["error_type"].fillna("").eq("normal_success")

    meas = pd.merge_asof(
        meas.sort_values("client_ts_start"),
        thermal.sort_values("thermal_ts"),
        left_on="client_ts_start",
        right_on="thermal_ts",
        direction="nearest",
        tolerance=pd.Timedelta(seconds=2),
    )
    meas["overhead_ms"] = meas["e2e_latency_ms"] - meas["server_total_latency_ms"]
    meas.to_csv(aligned_csv, index=False)

    rows = []
    group_cols = ["cycle_index", "phase"]
    for keys, phase_df in meas.groupby(group_cols, dropna=False):
        cycle_index, phase = keys
        row = {
            "cycle_index": int(cycle_index) if pd.notna(cycle_index) else -1,
            "phase": phase if pd.notna(phase) else "unknown",
            "rows": len(phase_df),
            "success_rows": int(phase_df["success_bool"].sum()),
            "success_rate": round(float(phase_df["success_bool"].mean()), 6) if len(phase_df) else None,
        }
        clean = phase_df[phase_df["success_bool"]].copy()
        for col in [
            "e2e_latency_ms",
            "server_latency_ms",
            "server_total_latency_ms",
            "overhead_ms",
            "gpu_temp_c",
            "gpu_fan_pct",
            "gpu_power_w",
            "gpu_util_pct",
            "gpu_clock_mhz",
        ]:
            summarize_series(clean[col], col, row)
        rows.append(row)

    per_cycle_df = pd.DataFrame(rows).sort_values(["cycle_index", "phase"])
    per_cycle_df.to_csv(per_cycle_csv, index=False)

    overall_rows = []
    for phase, phase_df in meas.groupby("phase", dropna=False):
        row = {
            "phase": phase if pd.notna(phase) else "unknown",
            "rows": len(phase_df),
            "success_rows": int(phase_df["success_bool"].sum()),
            "success_rate": round(float(phase_df["success_bool"].mean()), 6) if len(phase_df) else None,
        }
        clean = phase_df[phase_df["success_bool"]].copy()
        for col in [
            "e2e_latency_ms",
            "server_latency_ms",
            "server_total_latency_ms",
            "overhead_ms",
            "gpu_temp_c",
            "gpu_fan_pct",
            "gpu_power_w",
            "gpu_util_pct",
            "gpu_clock_mhz",
        ]:
            summarize_series(clean[col], col, row)
        overall_rows.append(row)
    overall_df = pd.DataFrame(overall_rows).sort_values("phase")
    overall_df.to_csv(overall_csv, index=False)

    duration_s = 0.0
    if len(meas) >= 2:
        duration_s = (meas["client_ts_start"].iloc[-1] - meas["client_ts_start"].iloc[0]).total_seconds()
    clean = meas[meas["success_bool"]].copy()

    lines = [
        f"RUN_DIR={run_dir}",
        f"aligned_csv={aligned_csv}",
        f"total_rows={len(meas)}",
        f"success_rows={len(clean)}",
        f"success_rate={(len(clean) / len(meas)) if len(meas) else 0.0:.6f}",
        f"observed_duration_s={duration_s:.3f}",
        f"achieved_rps={(len(meas) / duration_s) if duration_s > 0 else 0.0:.6f}",
        "",
        f"per_cycle_csv={per_cycle_csv}",
        f"overall_phase_csv={overall_csv}",
        "",
    ]

    for _, row in per_cycle_df.iterrows():
        lines.append(f"[cycle={row['cycle_index']} phase={row['phase']}] rows={row['rows']} success_rate={row['success_rate']}")
        for key in [
            "e2e_latency_ms_mean",
            "e2e_latency_ms_p95",
            "server_latency_ms_mean",
            "server_latency_ms_p95",
            "gpu_temp_c_mean",
            "gpu_temp_c_max",
            "gpu_fan_pct_mean",
            "gpu_power_w_mean",
            "gpu_util_pct_mean",
            "gpu_clock_mhz_mean",
        ]:
            if key in row and pd.notna(row[key]):
                lines.append(f"{key}={row[key]}")
        lines.append("")

    out_txt.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
