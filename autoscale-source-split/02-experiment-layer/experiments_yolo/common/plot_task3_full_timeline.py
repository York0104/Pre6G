#!/usr/bin/env python3
import sys
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

plt.rcParams["figure.dpi"] = 140

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

def load_gpu_df(run_dir: Path):
    path = run_dir / "nvidia_smi_gpu_1s.csv"
    df = pd.read_csv(path)

    ts_cols = [c for c in df.columns if "timestamp" in c.lower()]
    if not ts_cols:
        raise RuntimeError("nvidia_smi_gpu_1s.csv 找不到 timestamp 欄位")
    ts_col = ts_cols[0]

    raw_ts = pd.to_datetime(df[ts_col], errors="coerce")

    # nvidia-smi 通常是 node local time（你的情況通常是 Asia/Taipei）
    if getattr(raw_ts.dt, "tz", None) is None:
        df["_gpu_ts"] = raw_ts.dt.tz_localize("Asia/Taipei").dt.tz_convert("UTC")
    else:
        df["_gpu_ts"] = raw_ts.dt.tz_convert("UTC")

    df = df.dropna(subset=["_gpu_ts"]).reset_index(drop=True)

    gpu_col = [c for c in df.columns if "utilization.gpu" in c]
    if not gpu_col:
        raise RuntimeError("nvidia_smi_gpu_1s.csv 找不到 utilization.gpu 欄位")
    gpu_col = gpu_col[0]

    df["gpu_util"] = parse_numeric(df[gpu_col])
    return df

def load_measurement_df(run_dir: Path, t0):
    path = run_dir / "measurement_raw.csv"
    df = pd.read_csv(path)

    df["client_ts_start"] = pd.to_datetime(df["client_ts_start"], utc=True, errors="coerce")
    df = df.dropna(subset=["client_ts_start"]).sort_values("client_ts_start").reset_index(drop=True)
    df["t_rel_s"] = (df["client_ts_start"] - t0).dt.total_seconds()

    # 只保留正常成功資料
    if "error_type" in df.columns:
        clean = df[df["error_type"].fillna("") == "normal_success"].copy()
    else:
        clean = df[df["success"] == True].copy()

    clean = clean.sort_values("t_rel_s").reset_index(drop=True)
    for col in ["e2e_latency_ms", "server_latency_ms", "server_total_latency_ms"]:
        if col in clean.columns:
            clean[col] = pd.to_numeric(clean[col], errors="coerce")
    clean["e2e_ma2"] = clean["e2e_latency_ms"].rolling(2, min_periods=1).mean()
    clean["server_ma5"] = clean["server_latency_ms"].rolling(5, min_periods=1).mean()
    if "server_total_latency_ms" in clean.columns:
        clean["overhead_ms"] = clean["e2e_latency_ms"] - clean["server_total_latency_ms"]
        clean["server_total_ma5"] = clean["server_total_latency_ms"].rolling(5, min_periods=1).mean()
        clean["overhead_ma5"] = clean["overhead_ms"].rolling(5, min_periods=1).mean()
    else:
        clean["server_total_latency_ms"] = pd.NA
        clean["server_total_ma5"] = pd.NA
        clean["overhead_ms"] = pd.NA
        clean["overhead_ma5"] = pd.NA
    return df, clean

def load_stable_windows(run_dir: Path):
    path = run_dir / "stable_windows.csv"
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=["window_id", "start_s", "end_s", "duration_s"])

def shade_stable(ax, stable_df):
    if stable_df.empty:
        return
    for i, row in stable_df.iterrows():
        label = "stable window" if i == 0 else None
        ax.axvspan(
            float(row["start_s"]),
            float(row["end_s"]),
            color="orange",
            alpha=0.15,
            label=label,
        )

def save_plot(fig, path: Path):
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"saved: {path}")

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 common/plot_task3_full_timeline.py <RUN_DIR>")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    plot_dir = run_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    gpu_df = load_gpu_df(run_dir)
    t0 = gpu_df["_gpu_ts"].iloc[0]
    gpu_df["t_rel_s"] = (gpu_df["_gpu_ts"] - t0).dt.total_seconds()

    raw_meas_df, meas_df = load_measurement_df(run_dir, t0)
    stable_df = load_stable_windows(run_dir)

    # 圖 1：完整時間軸 E2E latency
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(meas_df["t_rel_s"], meas_df["e2e_latency_ms"], marker="o", markersize=3, linewidth=1, label="measurement e2e latency")
    shade_stable(ax, stable_df)
    ax.set_title("Task 3 Full Timeline: Time vs End-to-end Latency")
    ax.set_xlabel("Time from GPU monitor start (s)")
    ax.set_ylabel("End-to-end latency (ms)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save_plot(fig, plot_dir / "fig1_full_time_e2e_latency.png")

    # 圖 2：完整時間軸 E2E moving average
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(meas_df["t_rel_s"], meas_df["e2e_ma2"], marker="o", markersize=3, linewidth=1, label="measurement e2e latency MA(2)")
    shade_stable(ax, stable_df)
    ax.set_title("Task 3 Full Timeline: Time vs End-to-end Moving Average Latency")
    ax.set_xlabel("Time from GPU monitor start (s)")
    ax.set_ylabel("End-to-end moving average latency (ms)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save_plot(fig, plot_dir / "fig2_full_time_e2e_latency_ma2.png")

    # 圖 3：完整時間軸 server latency
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(meas_df["t_rel_s"], meas_df["server_latency_ms"], marker="o", markersize=3, linewidth=1, label="measurement server latency")
    shade_stable(ax, stable_df)
    ax.set_title("Task 3 Full Timeline: Time vs Server Latency")
    ax.set_xlabel("Time from GPU monitor start (s)")
    ax.set_ylabel("Server latency (ms)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save_plot(fig, plot_dir / "fig3_full_time_server_latency.png")

    # 圖 4：完整時間軸 server moving average
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(meas_df["t_rel_s"], meas_df["server_ma5"], marker="o", markersize=3, linewidth=1, label="measurement server latency MA(5)")
    shade_stable(ax, stable_df)
    ax.set_title("Task 3 Full Timeline: Time vs Server Moving Average Latency")
    ax.set_xlabel("Time from GPU monitor start (s)")
    ax.set_ylabel("Server moving average latency (ms)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save_plot(fig, plot_dir / "fig4_full_time_server_latency_ma5.png")

    # 圖 5：完整時間軸 server total latency
    if meas_df["server_total_latency_ms"].notna().any():
        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(meas_df["t_rel_s"], meas_df["server_total_latency_ms"], marker="o", markersize=3, linewidth=1, label="measurement server total latency")
        shade_stable(ax, stable_df)
        ax.set_title("Task 3 Full Timeline: Time vs Server Total Latency")
        ax.set_xlabel("Time from GPU monitor start (s)")
        ax.set_ylabel("Server total latency (ms)")
        ax.grid(True, alpha=0.3)
        ax.legend()
        save_plot(fig, plot_dir / "fig5_full_time_server_total_latency.png")

        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(meas_df["t_rel_s"], meas_df["server_total_ma5"], marker="o", markersize=3, linewidth=1, label="measurement server total latency MA(5)")
        shade_stable(ax, stable_df)
        ax.set_title("Task 3 Full Timeline: Time vs Server Total Moving Average Latency")
        ax.set_xlabel("Time from GPU monitor start (s)")
        ax.set_ylabel("Server total moving average latency (ms)")
        ax.grid(True, alpha=0.3)
        ax.legend()
        save_plot(fig, plot_dir / "fig6_full_time_server_total_latency_ma5.png")

        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(meas_df["t_rel_s"], meas_df["overhead_ms"], marker="o", markersize=3, linewidth=1, label="measurement overhead")
        shade_stable(ax, stable_df)
        ax.set_title("Task 3 Full Timeline: Time vs Overhead")
        ax.set_xlabel("Time from GPU monitor start (s)")
        ax.set_ylabel("Overhead (ms)")
        ax.grid(True, alpha=0.3)
        ax.legend()
        save_plot(fig, plot_dir / "fig7_full_time_overhead.png")

        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(meas_df["t_rel_s"], meas_df["overhead_ma5"], marker="o", markersize=3, linewidth=1, label="measurement overhead MA(5)")
        shade_stable(ax, stable_df)
        ax.set_title("Task 3 Full Timeline: Time vs Overhead Moving Average")
        ax.set_xlabel("Time from GPU monitor start (s)")
        ax.set_ylabel("Overhead moving average (ms)")
        ax.grid(True, alpha=0.3)
        ax.legend()
        save_plot(fig, plot_dir / "fig8_full_time_overhead_ma5.png")

    # 圖 9：完整時間軸 GPU utilization
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(gpu_df["t_rel_s"], gpu_df["gpu_util"], linewidth=1.2, label="GPU utilization")
    shade_stable(ax, stable_df)
    ax.set_title("Task 3 Full Timeline: Time vs GPU Utilization")
    ax.set_xlabel("Time from GPU monitor start (s)")
    ax.set_ylabel("GPU utilization (%)")
    ax.set_ylim(-2, 102)
    ax.grid(True, alpha=0.3)
    ax.legend()
    save_plot(fig, plot_dir / "fig9_full_time_gpu_utilization.png")

    print("\n[Done]")
    print("Generated:")
    generated = [
        plot_dir / "fig1_full_time_e2e_latency.png",
        plot_dir / "fig2_full_time_e2e_latency_ma2.png",
        plot_dir / "fig3_full_time_server_latency.png",
        plot_dir / "fig4_full_time_server_latency_ma5.png",
    ]
    if meas_df["server_total_latency_ms"].notna().any():
        generated.extend([
            plot_dir / "fig5_full_time_server_total_latency.png",
            plot_dir / "fig6_full_time_server_total_latency_ma5.png",
            plot_dir / "fig7_full_time_overhead.png",
            plot_dir / "fig8_full_time_overhead_ma5.png",
        ])
    generated.append(plot_dir / "fig9_full_time_gpu_utilization.png")
    for p in generated:
        print(p)

if __name__ == "__main__":
    main()
