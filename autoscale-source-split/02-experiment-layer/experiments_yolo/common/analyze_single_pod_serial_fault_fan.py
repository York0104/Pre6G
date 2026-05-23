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
    numeric_cols = [
        "elapsed_s",
        "phase_elapsed_s",
        "gpu_temp_c",
        "gpu_util_pct",
        "gpu_power_w",
        "gpu_fan_pct",
        "gpu_clock_mhz",
        "gpu_mem_clock_mhz",
        "stable_counter_s",
    ]
    for col in numeric_cols:
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
        print("Usage: python3 analyze_single_pod_serial_fault_fan.py <RUN_DIR>")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    meas_path = run_dir / "measurement_raw.csv"
    thermal_path = run_dir / "thermal_cycle" / "worker_logs" / "thermal.csv"
    out_csv = run_dir / "thermal_phase_summary.csv"
    out_txt = run_dir / "fault_fan_analysis.txt"
    aligned_csv = run_dir / "aligned_serial_thermal.csv"

    if not meas_path.exists():
        raise FileNotFoundError(meas_path)
    if not thermal_path.exists():
        raise FileNotFoundError(thermal_path)

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
    for phase, phase_df in meas.groupby("phase", dropna=False):
        row = {
            "phase": phase if pd.notna(phase) else "unknown",
            "rows": len(phase_df),
            "success_rows": int(phase_df["success_bool"].sum()),
            "success_rate": round(float(phase_df["success_bool"].mean()), 6) if len(phase_df) else None,
        }
        clean = phase_df[phase_df["success_bool"]].copy()
        summarize_series(clean["e2e_latency_ms"], "e2e_latency_ms", row)
        summarize_series(clean["server_latency_ms"], "server_latency_ms", row)
        summarize_series(clean["server_total_latency_ms"], "server_total_latency_ms", row)
        summarize_series(clean["overhead_ms"], "overhead_ms", row)
        summarize_series(clean["gpu_temp_c"], "gpu_temp_c", row)
        summarize_series(clean["gpu_fan_pct"], "gpu_fan_pct", row)
        summarize_series(clean["gpu_power_w"], "gpu_power_w", row)
        summarize_series(clean["gpu_util_pct"], "gpu_util_pct", row)
        rows.append(row)

    summary_df = pd.DataFrame(rows)
    summary_df.to_csv(out_csv, index=False)

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
    ]

    for _, row in summary_df.iterrows():
        lines.append(f"[phase={row['phase']}] rows={row['rows']} success_rate={row['success_rate']}")
        for key in [
            "e2e_latency_ms_mean",
            "e2e_latency_ms_p95",
            "server_latency_ms_mean",
            "server_latency_ms_p95",
            "server_total_latency_ms_mean",
            "server_total_latency_ms_p95",
            "gpu_temp_c_mean",
            "gpu_temp_c_max",
            "gpu_fan_pct_mean",
            "gpu_fan_pct_p95",
            "gpu_power_w_mean",
            "gpu_power_w_p95",
            "gpu_util_pct_mean",
            "gpu_util_pct_p95",
        ]:
            if key in row and pd.notna(row[key]):
                lines.append(f"{key}={row[key]}")
        lines.append("")

    out_txt.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
