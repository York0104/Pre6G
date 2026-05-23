import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def find_col(cols, keyword):
    for c in cols:
        if keyword in c:
            return c
    raise KeyError(f"Cannot find column containing: {keyword}")

def parse_numeric_series(df, col):
    return (
        df[col].astype(str)
        .str.replace(" %", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace(" W", "", regex=False)
        .str.replace(" MiB", "", regex=False)
        .str.replace(" MHz", "", regex=False)
        .str.strip()
        .replace("", np.nan)
        .astype(float)
    )

def load_stable_windows(run_dir: Path):
    path = run_dir / "stable_windows.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    needed = {"window_id", "start_s", "end_s"}
    if not needed.issubset(df.columns):
        print(f"[WARN] stable_windows.csv exists but missing columns: {needed - set(df.columns)}")
        return None
    return df

def add_stable_spans(ax, stable_df):
    if stable_df is None or stable_df.empty:
        return
    for _, row in stable_df.iterrows():
        ax.axvspan(row["start_s"], row["end_s"], color="orange", alpha=0.18)
    ax.axvspan(-1, -1, color="orange", alpha=0.18, label="stable window")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 plot_resource_overview.py <RUN_DIR>")
        sys.exit(1)

    run_dir = Path(sys.argv[1]).resolve()
    csv_path = run_dir / "nvidia_smi_gpu_1s.csv"
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    if not csv_path.exists():
        print(f"[ERROR] File not found: {csv_path}")
        sys.exit(1)

    print(f"[INFO] RUN_DIR = {run_dir}")
    print(f"[INFO] Reading {csv_path}")

    df = pd.read_csv(csv_path)

    gpu_col   = find_col(df.columns, "utilization.gpu")
    mem_col   = find_col(df.columns, "utilization.memory")
    power_col = find_col(df.columns, "power.draw")
    temp_col  = find_col(df.columns, "temperature.gpu")

    df["gpu_util"] = parse_numeric_series(df, gpu_col)
    df["mem_util"] = parse_numeric_series(df, mem_col)
    df["power_w"]  = parse_numeric_series(df, power_col)
    df["temp_c"]   = parse_numeric_series(df, temp_col)
    df["t_rel_s"]  = np.arange(len(df))

    stable_df = load_stable_windows(run_dir)

    fig, axs = plt.subplots(2, 2, figsize=(16, 10), sharex=True)
    fig.suptitle("Task 3 Resource Overview", fontsize=18)

    # 1. GPU utilization
    axs[0, 0].plot(
        df["t_rel_s"], df["gpu_util"],
        marker='o', markersize=2, linewidth=1.2,
        label="GPU utilization"
    )
    add_stable_spans(axs[0, 0], stable_df)
    axs[0, 0].set_title("GPU Utilization")
    axs[0, 0].set_ylabel("Utilization (%)")
    axs[0, 0].grid(True, alpha=0.3)
    axs[0, 0].legend()

    # 2. GPU memory utilization
    axs[0, 1].plot(
        df["t_rel_s"], df["mem_util"],
        marker='o', markersize=2, linewidth=1.2,
        color="tab:green", label="GPU memory utilization"
    )
    add_stable_spans(axs[0, 1], stable_df)
    axs[0, 1].set_title("GPU Memory Utilization")
    axs[0, 1].set_ylabel("Utilization (%)")
    axs[0, 1].grid(True, alpha=0.3)
    axs[0, 1].legend()

    # 3. Power draw
    axs[1, 0].plot(
        df["t_rel_s"], df["power_w"],
        marker='o', markersize=2, linewidth=1.2,
        color="tab:red", label="Power draw"
    )
    add_stable_spans(axs[1, 0], stable_df)
    axs[1, 0].set_title("GPU Power Draw")
    axs[1, 0].set_xlabel("Time from GPU monitor start (s)")
    axs[1, 0].set_ylabel("Power (W)")
    axs[1, 0].grid(True, alpha=0.3)
    axs[1, 0].legend()

    # 4. Temperature
    axs[1, 1].plot(
        df["t_rel_s"], df["temp_c"],
        marker='o', markersize=2, linewidth=1.2,
        color="tab:orange", label="GPU temperature"
    )
    add_stable_spans(axs[1, 1], stable_df)
    axs[1, 1].set_title("GPU Temperature")
    axs[1, 1].set_xlabel("Time from GPU monitor start (s)")
    axs[1, 1].set_ylabel("Temperature (°C)")
    axs[1, 1].grid(True, alpha=0.3)
    axs[1, 1].legend()

    plt.tight_layout()

    output_path = plots_dir / "gpu_resource_overview.png"
    plt.savefig(output_path, dpi=180)
    plt.close(fig)

    print(f"[OK] Saved: {output_path}")

if __name__ == "__main__":
    main()
