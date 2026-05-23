#!/usr/bin/env python3
# /home/iccls2/AutoScale/experiments/thermal_analysis/plot_latency_results.py
import argparse
import csv
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


PHASE_ORDER = ["warmup", "normal_hold", "fault_ramp_up", "fault_hold"]


def to_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def ecdf(values):
    x = np.sort(np.asarray(values, dtype=float))
    y = np.arange(1, len(x) + 1) / len(x)
    return x, y


def percentile(arr, q):
    if len(arr) == 0:
        return np.nan
    return float(np.percentile(arr, q))


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for phase in PHASE_ORDER:
        g = df[df["aligned_phase"] == phase].copy()
        if g.empty:
            continue

        client = g["latency_ms_client"].dropna().to_numpy()
        server = g["server_latency_ms"].dropna().to_numpy()
        temp = g["aligned_gpu_temp_c"].dropna().to_numpy()
        power = g["aligned_gpu_power_w"].dropna().to_numpy()

        rows.append({
            "phase": phase,
            "count": len(g),
            "client_mean_ms": round(float(np.mean(client)), 3) if len(client) else np.nan,
            "client_p50_ms": round(percentile(client, 50), 3) if len(client) else np.nan,
            "client_p95_ms": round(percentile(client, 95), 3) if len(client) else np.nan,
            "client_p99_ms": round(percentile(client, 99), 3) if len(client) else np.nan,
            "server_mean_ms": round(float(np.mean(server)), 3) if len(server) else np.nan,
            "server_p50_ms": round(percentile(server, 50), 3) if len(server) else np.nan,
            "server_p95_ms": round(percentile(server, 95), 3) if len(server) else np.nan,
            "server_p99_ms": round(percentile(server, 99), 3) if len(server) else np.nan,
            "temp_mean_c": round(float(np.mean(temp)), 3) if len(temp) else np.nan,
            "power_mean_w": round(float(np.mean(power)), 3) if len(power) else np.nan,
        })
    return pd.DataFrame(rows)


def phase_boxplot(df, column, title, ylabel, outpath, logy=False, clip_q=None):
    plot_df = df[df["aligned_phase"].isin(PHASE_ORDER)].copy()
    if clip_q is not None:
        upper = plot_df[column].quantile(clip_q)
        plot_df = plot_df[plot_df[column] <= upper]

    data = [plot_df.loc[plot_df["aligned_phase"] == phase, column].dropna().to_numpy()
            for phase in PHASE_ORDER if phase in plot_df["aligned_phase"].unique()]
    labels = [phase for phase in PHASE_ORDER if phase in plot_df["aligned_phase"].unique()]

    plt.figure(figsize=(10, 6))
    plt.boxplot(data, labels=labels, showfliers=True)
    if logy:
        plt.yscale("log")
    plt.title(title)
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(outpath, dpi=160)
    plt.close()


def phase_violin(df, column, title, ylabel, outpath, clip_q=None):
    plot_df = df[df["aligned_phase"].isin(PHASE_ORDER)].copy()
    if clip_q is not None:
        upper = plot_df[column].quantile(clip_q)
        plot_df = plot_df[plot_df[column] <= upper]

    data = [plot_df.loc[plot_df["aligned_phase"] == phase, column].dropna().to_numpy()
            for phase in PHASE_ORDER if phase in plot_df["aligned_phase"].unique()]
    labels = [phase for phase in PHASE_ORDER if phase in plot_df["aligned_phase"].unique()]

    plt.figure(figsize=(10, 6))
    parts = plt.violinplot(data, showmeans=False, showmedians=True, showextrema=True)
    plt.xticks(np.arange(1, len(labels) + 1), labels)
    plt.title(title)
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(outpath, dpi=160)
    plt.close()


def plot_ecdf(df, column, title, xlabel, outpath):
    plt.figure(figsize=(10, 6))
    for phase in PHASE_ORDER:
        vals = df.loc[df["aligned_phase"] == phase, column].dropna().to_numpy()
        if len(vals) == 0:
            continue
        x, y = ecdf(vals)
        plt.step(x, y, where="post", label=phase)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel("ECDF")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=160)
    plt.close()


def plot_binned_relation(df, x_col, y_col, title, xlabel, ylabel, outpath, bin_width):
    plot_df = df[[x_col, y_col, "aligned_phase"]].copy().dropna()
    plot_df = plot_df[plot_df["aligned_phase"].isin(["normal_hold", "fault_hold"])]

    if plot_df.empty:
        return

    xmin = math.floor(plot_df[x_col].min() / bin_width) * bin_width
    xmax = math.ceil(plot_df[x_col].max() / bin_width) * bin_width + bin_width
    bins = np.arange(xmin, xmax + 1e-9, bin_width)
    plot_df["bin"] = pd.cut(plot_df[x_col], bins=bins, include_lowest=True, right=False)

    grouped = plot_df.groupby("bin", observed=True)[y_col].agg(
        median="median",
        p25=lambda s: np.percentile(s, 25),
        p75=lambda s: np.percentile(s, 75),
        p95=lambda s: np.percentile(s, 95),
        count="count",
    ).reset_index()

    centers = []
    for interval in grouped["bin"]:
        centers.append((interval.left + interval.right) / 2)

    plt.figure(figsize=(10, 6))
    plt.plot(centers, grouped["median"], marker="o", label="median")
    plt.plot(centers, grouped["p95"], marker="o", linestyle="--", label="p95")
    plt.fill_between(centers, grouped["p25"], grouped["p75"], alpha=0.25, label="p25-p75")
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=160)
    plt.close()


def plot_timeseries(df, server_clip_q, outpath):
    plot_df = df.copy()
    plot_df = plot_df.sort_values("req_id")
    if "req_id" not in plot_df.columns:
        plot_df["req_id"] = np.arange(1, len(plot_df) + 1)

    server_upper = plot_df["server_latency_ms"].quantile(server_clip_q)
    client_upper = plot_df["latency_ms_client"].quantile(server_clip_q)

    plot_df["server_plot"] = plot_df["server_latency_ms"].clip(upper=server_upper)
    plot_df["client_plot"] = plot_df["latency_ms_client"].clip(upper=client_upper)

    plot_df["server_ma"] = plot_df["server_plot"].rolling(20, min_periods=1).median()
    plot_df["client_ma"] = plot_df["client_plot"].rolling(20, min_periods=1).median()

    plt.figure(figsize=(12, 6))
    plt.plot(plot_df["req_id"], plot_df["server_plot"], alpha=0.35, label="server latency (clipped)")
    plt.plot(plot_df["req_id"], plot_df["server_ma"], linewidth=2, label="server latency (rolling median)")
    plt.plot(plot_df["req_id"], plot_df["client_plot"], alpha=0.2, label="client latency (clipped)")
    plt.plot(plot_df["req_id"], plot_df["client_ma"], linewidth=2, label="client latency (rolling median)")
    plt.title("Latency Time Series (clipped at high quantile)")
    plt.xlabel("Request ID")
    plt.ylabel("Latency (ms)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=160)
    plt.close()


def plot_outlier_table(summary_df, outpath):
    fig, ax = plt.subplots(figsize=(12, max(2, 0.7 * len(summary_df) + 1.5)))
    ax.axis("off")
    table_data = [summary_df.columns.tolist()] + summary_df.astype(str).values.tolist()
    table = ax.table(cellText=table_data, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.4)
    plt.title("Latency Summary Table", pad=12)
    plt.tight_layout()
    plt.savefig(outpath, dpi=160, bbox_inches="tight")
    plt.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="aligned_service_metrics.csv")
    ap.add_argument("--outdir", required=True, help="output directory for figures")
    ap.add_argument("--clip-quantile", type=float, default=0.99, help="upper quantile for clipped visualizations")
    ap.add_argument("--temp-bin-width", type=float, default=2.0)
    ap.add_argument("--power-bin-width", type=float, default=10.0)
    args = ap.parse_args()

    outdir = Path(args.outdir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(Path(args.csv).expanduser())

    # Normalize columns
    numeric_cols = [
        "req_id",
        "latency_ms_client",
        "server_latency_ms",
        "aligned_gpu_temp_c",
        "aligned_gpu_power_w",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = to_numeric(df[col])

    if "aligned_phase" not in df.columns:
        raise ValueError("CSV missing aligned_phase column")
    if "req_id" not in df.columns:
        df["req_id"] = np.arange(1, len(df) + 1)

    summary_df = build_summary(df)
    summary_df.to_csv(outdir / "latency_summary_table.csv", index=False)

    plot_ecdf(
        df,
        "server_latency_ms",
        "Server Latency ECDF",
        "Server Latency (ms)",
        outdir / "server_latency_ecdf.png",
    )

    plot_ecdf(
        df,
        "latency_ms_client",
        "Client Latency ECDF",
        "Client Latency (ms)",
        outdir / "client_latency_ecdf.png",
    )

    phase_boxplot(
        df,
        "server_latency_ms",
        "Server Latency by Phase (log scale)",
        "Server Latency (ms)",
        outdir / "server_latency_by_phase_log.png",
        logy=True,
        clip_q=None,
    )

    phase_boxplot(
        df,
        "latency_ms_client",
        "Client Latency by Phase (log scale)",
        "Client Latency (ms)",
        outdir / "client_latency_by_phase_log.png",
        logy=True,
        clip_q=None,
    )

    phase_violin(
        df,
        "server_latency_ms",
        f"Server Latency by Phase (clipped at q={args.clip_quantile})",
        "Server Latency (ms)",
        outdir / "server_latency_by_phase_violin.png",
        clip_q=args.clip_quantile,
    )

    plot_binned_relation(
        df,
        "aligned_gpu_temp_c",
        "server_latency_ms",
        "Server Latency vs GPU Temp (binned)",
        "GPU Temp (C)",
        "Server Latency (ms)",
        outdir / "server_latency_vs_temp_binned.png",
        bin_width=args.temp_bin_width,
    )

    plot_binned_relation(
        df,
        "aligned_gpu_power_w",
        "server_latency_ms",
        "Server Latency vs GPU Power (binned)",
        "GPU Power (W)",
        "Server Latency (ms)",
        outdir / "server_latency_vs_power_binned.png",
        bin_width=args.power_bin_width,
    )

    plot_timeseries(
        df,
        server_clip_q=args.clip_quantile,
        outpath=outdir / "latency_timeseries_clipped.png",
    )

    plot_outlier_table(summary_df, outdir / "latency_summary_table.png")

    # Save an outlier-focused CSV for quick inspection
    fault_hold = df[df["aligned_phase"] == "fault_hold"].copy()
    if not fault_hold.empty:
        client_thr = fault_hold["latency_ms_client"].quantile(0.99)
        server_thr = fault_hold["server_latency_ms"].quantile(0.99)
        outliers = fault_hold[
            (fault_hold["latency_ms_client"] >= client_thr) |
            (fault_hold["server_latency_ms"] >= server_thr)
        ].copy()
        cols = [c for c in [
            "client_ts", "req_id", "latency_ms_client", "server_latency_ms",
            "aligned_phase", "aligned_binary_label", "aligned_gpu_temp_c",
            "aligned_gpu_power_w", "aligned_gpu_util_pct"
        ] if c in outliers.columns]
        outliers = outliers[cols].sort_values(["latency_ms_client", "server_latency_ms"], ascending=False)
        outliers.to_csv(outdir / "fault_hold_outliers.csv", index=False)

    print(f"written: {outdir / 'latency_summary_table.csv'}")
    print(f"written: {outdir / 'server_latency_ecdf.png'}")
    print(f"written: {outdir / 'client_latency_ecdf.png'}")
    print(f"written: {outdir / 'server_latency_by_phase_log.png'}")
    print(f"written: {outdir / 'client_latency_by_phase_log.png'}")
    print(f"written: {outdir / 'server_latency_by_phase_violin.png'}")
    print(f"written: {outdir / 'server_latency_vs_temp_binned.png'}")
    print(f"written: {outdir / 'server_latency_vs_power_binned.png'}")
    print(f"written: {outdir / 'latency_timeseries_clipped.png'}")
    print(f"written: {outdir / 'latency_summary_table.png'}")
    if (outdir / "fault_hold_outliers.csv").exists():
        print(f"written: {outdir / 'fault_hold_outliers.csv'}")


if __name__ == "__main__":
    main()
