#!/usr/bin/env python3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

AXIS_LABEL_FONTSIZE = 16
TICK_LABEL_FONTSIZE = 13
LEGEND_FONTSIZE = 12


def add_phase_guides(ax, df, x_col="t_rel_s"):
    if "phase" not in df.columns:
        return
    cols = [x_col, "phase"]
    if "cycle_index" in df.columns:
        cols.append("cycle_index")
    tmp = df[cols].dropna(subset=[x_col, "phase"]).copy()
    if tmp.empty:
        return
    prev = None
    for _, row in tmp.iterrows():
        label = str(row["phase"])
        if "cycle_index" in tmp.columns and pd.notna(row["cycle_index"]):
            label = f"c{int(row['cycle_index'])}:{label}"
        if label != prev:
            ax.axvline(row[x_col], color="gray", linestyle="--", alpha=0.2)
            prev = label


def prep_df(run_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(run_dir / "aligned_serial_thermal.csv")
    df["client_ts_start"] = pd.to_datetime(df["client_ts_start"], utc=True, errors="coerce")
    df = df.dropna(subset=["client_ts_start"]).copy()
    df["t_rel_s"] = (df["client_ts_start"] - df["client_ts_start"].iloc[0]).dt.total_seconds()
    for col in [
        "cycle_index",
        "gpu_fan_pct",
        "gpu_temp_c",
        "gpu_clock_mhz",
        "gpu_util_pct",
        "server_latency_ms",
        "server_total_latency_ms",
        "e2e_latency_ms",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def save_plot(df: pd.DataFrame, out_path: Path, panels, x_col="t_rel_s", xlabel="Time from first request (s)"):
    fig, axs = plt.subplots(len(panels), 1, figsize=(14, 3 * len(panels)), sharex=True)
    if len(panels) == 1:
        axs = [axs]
    for ax, panel in zip(axs, panels):
        for series in panel["series"]:
            ax.plot(df[x_col], df[series["col"]], color=series["color"], linewidth=1.5, label=series["label"])
        ax.set_ylabel(panel["ylabel"], fontsize=AXIS_LABEL_FONTSIZE)
        ax.tick_params(axis="both", labelsize=TICK_LABEL_FONTSIZE)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left", fontsize=LEGEND_FONTSIZE)
        add_phase_guides(ax, df, x_col=x_col)
    axs[-1].set_xlabel(xlabel, fontsize=AXIS_LABEL_FONTSIZE)
    axs[-1].tick_params(axis="both", labelsize=TICK_LABEL_FONTSIZE)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=160)
    plt.close(fig)


def plot_pair(df: pd.DataFrame, out_dir: Path, prefix: str, x_col="t_rel_s", xlabel="Time from first request (s)"):
    save_plot(
        df,
        out_dir / f"{prefix}_temp_fan_timeseries.png",
        [
            {"ylabel": "Fan (%)", "series": [{"col": "gpu_fan_pct", "color": "tab:blue", "label": "GPU fan (%)"}]},
            {"ylabel": "Temp (C)", "series": [{"col": "gpu_temp_c", "color": "tab:red", "label": "GPU temp (C)"}]},
            {"ylabel": "SM clock (MHz)", "series": [{"col": "gpu_clock_mhz", "color": "tab:purple", "label": "SM clock (MHz)"}]},
            {"ylabel": "GPU util (%)", "series": [{"col": "gpu_util_pct", "color": "tab:green", "label": "GPU util (%)"}]},
        ],
        x_col=x_col,
        xlabel=xlabel,
    )
    print(f"saved: {out_dir / f'{prefix}_temp_fan_timeseries.png'}")

    save_plot(
        df,
        out_dir / f"{prefix}_temp_latency_overview.png",
        [
            {"ylabel": "Fan (%)", "series": [{"col": "gpu_fan_pct", "color": "tab:blue", "label": "GPU fan (%)"}]},
            {"ylabel": "Temp (C)", "series": [{"col": "gpu_temp_c", "color": "tab:red", "label": "GPU temp (C)"}]},
            {
                "ylabel": "Server Latency (ms)",
                "series": [
                    {"col": "server_latency_ms", "color": "tab:purple", "label": "server latency (ms)"},
                    {"col": "server_total_latency_ms", "color": "tab:brown", "label": "server total latency (ms)"},
                ],
            },
            {"ylabel": "E2E Latency (ms)", "series": [{"col": "e2e_latency_ms", "color": "tab:gray", "label": "e2e latency (ms)"}]},
        ],
        x_col=x_col,
        xlabel=xlabel,
    )
    print(f"saved: {out_dir / f'{prefix}_temp_latency_overview.png'}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 plot_single_pod_bgload_fan_cycle.py <RUN_DIR>")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    df = prep_df(run_dir)
    plot_pair(df, plots_dir, "bgload_cycle", x_col="t_rel_s", xlabel="Time from first request (s)")

    if "cycle_index" in df.columns:
        cycle_plots_dir = plots_dir / "cycles"
        cycle_plots_dir.mkdir(parents=True, exist_ok=True)
        cycle_ids = [int(x) for x in sorted(df["cycle_index"].dropna().unique()) if int(x) >= 1]
        for cycle_id in cycle_ids:
            cycle_df = df[df["cycle_index"] == cycle_id].copy()
            if cycle_df.empty:
                continue
            cycle_df["t_cycle_s"] = cycle_df["t_rel_s"] - cycle_df["t_rel_s"].iloc[0]
            plot_pair(
                cycle_df,
                cycle_plots_dir,
                f"cycle_{cycle_id:03d}",
                x_col="t_cycle_s",
                xlabel=f"Time within cycle {cycle_id} (s)",
            )


if __name__ == "__main__":
    main()
