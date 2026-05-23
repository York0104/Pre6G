#!/usr/bin/env python3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def add_phase_guides(ax, df):
    if "phase" not in df.columns:
        return
    tmp = df[["t_rel_s", "phase"]].dropna().copy()
    if tmp.empty:
        return
    tmp["phase"] = tmp["phase"].astype(str)
    prev = None
    for _, row in tmp.iterrows():
        if row["phase"] != prev:
            ax.axvline(row["t_rel_s"], color="gray", linestyle="--", alpha=0.22)
            prev = row["phase"]


def prep_df(run_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(run_dir / "aligned_serial_thermal.csv")
    df["client_ts_start"] = pd.to_datetime(df["client_ts_start"], utc=True, errors="coerce")
    df = df.dropna(subset=["client_ts_start"]).copy()
    df["t_rel_s"] = (df["client_ts_start"] - df["client_ts_start"].iloc[0]).dt.total_seconds()

    for col in [
        "gpu_temp_c",
        "gpu_fan_pct",
        "gpu_clock_mhz",
        "gpu_util_pct",
        "server_latency_ms",
        "server_total_latency_ms",
        "e2e_latency_ms",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def plot_temp_fan_clock_util(df: pd.DataFrame, out_path: Path):
    fig, axs = plt.subplots(4, 1, figsize=(14, 12), sharex=True)

    axs[0].plot(df["t_rel_s"], df["gpu_fan_pct"], color="tab:blue", linewidth=1.5, label="GPU fan (%)")
    axs[0].set_ylabel("Fan (%)")
    axs[0].grid(True, alpha=0.3)
    axs[0].legend(loc="upper left")
    add_phase_guides(axs[0], df)

    axs[1].plot(df["t_rel_s"], df["gpu_temp_c"], color="tab:red", linewidth=1.6, label="GPU temp (C)")
    axs[1].set_ylabel("Temp (C)")
    axs[1].grid(True, alpha=0.3)
    axs[1].legend(loc="upper left")
    add_phase_guides(axs[1], df)

    axs[2].plot(df["t_rel_s"], df["gpu_clock_mhz"], color="tab:purple", linewidth=1.5, label="SM clock (MHz)")
    axs[2].set_ylabel("SM clock (MHz)")
    axs[2].grid(True, alpha=0.3)
    axs[2].legend(loc="upper left")
    add_phase_guides(axs[2], df)

    axs[3].plot(df["t_rel_s"], df["gpu_util_pct"], color="tab:green", linewidth=1.5, label="GPU util (%)")
    axs[3].set_ylabel("GPU util (%)")
    axs[3].set_xlabel("Time from first request (s)")
    axs[3].grid(True, alpha=0.3)
    axs[3].legend(loc="upper left")
    add_phase_guides(axs[3], df)

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=160)
    plt.close(fig)


def plot_temp_fan_latency(df: pd.DataFrame, out_path: Path):
    fig, axs = plt.subplots(4, 1, figsize=(14, 12), sharex=True)

    axs[0].plot(df["t_rel_s"], df["gpu_fan_pct"], color="tab:blue", linewidth=1.5, label="GPU fan (%)")
    axs[0].set_ylabel("Fan (%)")
    axs[0].grid(True, alpha=0.3)
    axs[0].legend(loc="upper left")
    add_phase_guides(axs[0], df)

    axs[1].plot(df["t_rel_s"], df["gpu_temp_c"], color="tab:red", linewidth=1.6, label="GPU temp (C)")
    axs[1].set_ylabel("Temp (C)")
    axs[1].grid(True, alpha=0.3)
    axs[1].legend(loc="upper left")
    add_phase_guides(axs[1], df)

    axs[2].plot(df["t_rel_s"], df["server_latency_ms"], color="tab:purple", linewidth=1.5, label="server latency (ms)")
    if "server_total_latency_ms" in df.columns:
        axs[2].plot(
            df["t_rel_s"],
            df["server_total_latency_ms"],
            color="tab:brown",
            linewidth=1.3,
            alpha=0.85,
            label="server total latency (ms)",
        )
    axs[2].set_ylabel("Server Latency (ms)")
    axs[2].grid(True, alpha=0.3)
    axs[2].legend(loc="upper left")
    add_phase_guides(axs[2], df)

    axs[3].plot(df["t_rel_s"], df["e2e_latency_ms"], color="tab:gray", linewidth=1.5, label="e2e latency (ms)")
    axs[3].set_ylabel("E2E Latency (ms)")
    axs[3].set_xlabel("Time from first request (s)")
    axs[3].grid(True, alpha=0.3)
    axs[3].legend(loc="upper left")
    add_phase_guides(axs[3], df)

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=160)
    plt.close(fig)


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 plot_single_pod_serial_fault_fan.py <RUN_DIR>")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    clock_util_path = plots_dir / "fault_fan_temp_fan_timeseries.png"
    latency_path = plots_dir / "fault_fan_temp_latency_overview.png"

    df = prep_df(run_dir)
    plot_temp_fan_clock_util(df, clock_util_path)
    print(f"saved: {clock_util_path}")
    plot_temp_fan_latency(df, latency_path)
    print(f"saved: {latency_path}")


if __name__ == "__main__":
    main()
