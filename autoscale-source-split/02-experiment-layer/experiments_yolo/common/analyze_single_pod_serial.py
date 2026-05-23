#!/usr/bin/env python3
import sys
from pathlib import Path

import pandas as pd


def parse_numeric(series):
    return pd.to_numeric(
        series.astype(str)
        .str.replace(" %", "", regex=False)
        .str.replace(" W", "", regex=False)
        .str.replace(" MiB", "", regex=False)
        .str.replace(" MHz", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


def summarize_latency(df, label):
    out = [f"[{label}]"]
    out.append(f"rows={len(df)}")
    if len(df) == 0:
        return "\n".join(out)

    for col in ["e2e_latency_ms", "server_latency_ms", "server_total_latency_ms"]:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        out.append(
            f"{col}: mean={s.mean():.3f}, p50={s.quantile(0.5):.3f}, "
            f"p95={s.quantile(0.95):.3f}, p99={s.quantile(0.99):.3f}, max={s.max():.3f}"
        )
    return "\n".join(out)


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 analyze_single_pod_serial.py <RUN_DIR>")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    meas_path = run_dir / "measurement_raw.csv"
    gpu_path = run_dir / "nvidia_smi_gpu_1s.csv"
    out_path = run_dir / "serial_analysis.txt"
    phase_path = run_dir / "phase_summary.csv"

    if not meas_path.exists():
        raise FileNotFoundError(meas_path)
    if not gpu_path.exists():
        raise FileNotFoundError(gpu_path)

    meas = pd.read_csv(meas_path)
    gpu = pd.read_csv(gpu_path)

    meas["client_ts_start"] = pd.to_datetime(meas["client_ts_start"], utc=True, errors="coerce")
    meas = meas.dropna(subset=["client_ts_start"]).sort_values("client_ts_start").reset_index(drop=True)

    success = meas[meas["error_type"].fillna("") == "normal_success"].copy()

    duration_s = 0.0
    if len(meas) >= 2:
        duration_s = (meas["client_ts_start"].iloc[-1] - meas["client_ts_start"].iloc[0]).total_seconds()

    achieved_rps = (len(meas) / duration_s) if duration_s > 0 else 0.0
    success_rps = (len(success) / duration_s) if duration_s > 0 else 0.0

    ts_cols = [c for c in gpu.columns if "timestamp" in c.lower()]
    if not ts_cols:
        raise RuntimeError("nvidia_smi_gpu_1s.csv 找不到 timestamp 欄位")

    gpu["gpu_util"] = parse_numeric(gpu[[c for c in gpu.columns if "utilization.gpu" in c][0]])
    gpu["mem_util"] = parse_numeric(gpu[[c for c in gpu.columns if "utilization.memory" in c][0]])
    gpu["power_w"] = parse_numeric(gpu[[c for c in gpu.columns if "power.draw" in c][0]])
    gpu["temp_c"] = parse_numeric(gpu[[c for c in gpu.columns if "temperature.gpu" in c][0]])

    meas["t_rel_s"] = (meas["client_ts_start"] - meas["client_ts_start"].iloc[0]).dt.total_seconds()
    if len(meas) > 0:
        q1 = meas["t_rel_s"].quantile(1 / 3)
        q2 = meas["t_rel_s"].quantile(2 / 3)
        meas["phase"] = pd.cut(
            meas["t_rel_s"],
            bins=[-1e-9, q1, q2, meas["t_rel_s"].max() + 1e-9],
            labels=["early", "mid", "late"],
        )
    else:
        meas["phase"] = pd.Series(dtype="object")

    phase_rows = []
    for phase, phase_df in meas.groupby("phase", dropna=True):
        clean = phase_df[phase_df["error_type"].fillna("") == "normal_success"].copy()
        row = {"phase": phase, "rows": len(phase_df), "success_rows": len(clean)}
        for col in ["e2e_latency_ms", "server_latency_ms", "server_total_latency_ms"]:
            s = pd.to_numeric(clean[col], errors="coerce").dropna() if col in clean.columns else pd.Series(dtype=float)
            row[f"{col}_mean"] = round(s.mean(), 3) if len(s) else None
            row[f"{col}_p95"] = round(s.quantile(0.95), 3) if len(s) else None
        phase_rows.append(row)
    pd.DataFrame(phase_rows).to_csv(phase_path, index=False)

    lines = [
        f"RUN_DIR={run_dir}",
        f"total_rows={len(meas)}",
        f"success_rows={len(success)}",
        f"success_rate={(len(success) / len(meas)) if len(meas) else 0.0:.6f}",
        f"observed_duration_s={duration_s:.3f}",
        f"achieved_rps={achieved_rps:.6f}",
        f"successful_rps={success_rps:.6f}",
        "",
        summarize_latency(success, "clean_success"),
        "",
        "[gpu_summary]",
        (
            f"gpu_util: mean={gpu['gpu_util'].mean():.3f}, p95={gpu['gpu_util'].quantile(0.95):.3f}, "
            f"max={gpu['gpu_util'].max():.3f}"
        ),
        (
            f"mem_util: mean={gpu['mem_util'].mean():.3f}, p95={gpu['mem_util'].quantile(0.95):.3f}, "
            f"max={gpu['mem_util'].max():.3f}"
        ),
        (
            f"power_w: mean={gpu['power_w'].mean():.3f}, p95={gpu['power_w'].quantile(0.95):.3f}, "
            f"max={gpu['power_w'].max():.3f}"
        ),
        (
            f"temp_c: mean={gpu['temp_c'].mean():.3f}, p95={gpu['temp_c'].quantile(0.95):.3f}, "
            f"max={gpu['temp_c'].max():.3f}"
        ),
        "",
        f"phase_summary_csv={phase_path}",
    ]

    text = "\n".join(lines)
    out_path.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
