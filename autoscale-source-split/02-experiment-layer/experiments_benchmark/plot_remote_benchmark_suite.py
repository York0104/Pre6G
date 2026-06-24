#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


METRICS = [
    ("cpu_percent", "CPU", "#1f77b4", "-", 1.6, 2),
    ("ram_used_percent", "RAM", "#2ca02c", "--", 1.8, 3),
    ("gpu_util_percent", "GPU", "#ff7f0e", "-.", 1.4, 4),
    ("vram_used_percent", "VRAM", "#b22222", ":", 2.2, 5),
]

TASK_LABELS = {
    "cpu_bound": "CPU-bound Video Compression",
    "ram_bound": "RAM-bound Redis Stress",
    "vram_bound": "VRAM-bound Qwen3:32B",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Plot a 3-panel suite figure from remote benchmark runs.")
    parser.add_argument("--suite-dir", required=True, help="Suite run directory")
    parser.add_argument("--output", help="Optional output image path")
    parser.add_argument("--smooth-window", type=int, default=1, help="Rolling median window, 1 disables smoothing")
    return parser.parse_args()


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def rolling_median(values, window: int):
    if window <= 1:
        return values
    if window % 2 == 0:
        window += 1
    radius = window // 2
    smoothed = []
    for index in range(len(values)):
        left = max(0, index - radius)
        right = min(len(values), index + radius + 1)
        smoothed.append(median(values[left:right]))
    return smoothed


def load_manifest(path: Path):
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_monitor_csv(path: Path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                {
                    "elapsed_s": float(row["elapsed_s"]),
                    "cpu_percent": float(row["cpu_percent"]) if row["cpu_percent"] else None,
                    "ram_used_percent": float(row["ram_used_percent"]) if row["ram_used_percent"] else None,
                    "gpu_util_percent": float(row["gpu_util_percent"]) if row["gpu_util_percent"] else None,
                    "vram_used_percent": float(row["vram_used_percent"]) if row["vram_used_percent"] else None,
                }
            )
    return rows


def main():
    args = parse_args()
    suite_dir = resolve_path(args.suite_dir)
    manifest = load_manifest(suite_dir / "suite_manifest.csv")
    output = resolve_path(args.output) if args.output else suite_dir / "suite_resource_utilization.png"
    plotting_errors = []

    fig, axes = plt.subplots(len(manifest), 1, figsize=(14, 4.2 * max(1, len(manifest))), constrained_layout=True)
    if len(manifest) == 1:
        axes = [axes]

    for index, entry in enumerate(manifest):
        ax = axes[index]
        task = entry["task"]
        run_dir = resolve_path(entry["run_dir"])
        rows = load_monitor_csv(run_dir / "combined_monitor.csv")
        if not rows:
            plotting_errors.append({"task": task, "run_dir": str(run_dir), "error": "combined_monitor_missing"})
            ax.set_title(f"({chr(ord('a') + index)}) {TASK_LABELS.get(task, task)}", loc="left")
            ax.text(0.5, 0.5, "combined_monitor.csv missing", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            continue

        for key, label, color, linestyle, linewidth, zorder in METRICS:
            x = [row["elapsed_s"] for row in rows if row.get(key) is not None]
            y = [row[key] for row in rows if row.get(key) is not None]
            if not x:
                continue
            y = rolling_median(y, args.smooth_window)
            ax.plot(x, y, color=color, linestyle=linestyle, linewidth=linewidth, label=label, zorder=zorder)

        ax.set_ylim(0, 100)
        ax.set_ylabel("Util. (%)")
        ax.grid(True, axis="y", alpha=0.25)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_title(f"({chr(ord('a') + index)}) {TASK_LABELS.get(task, task)}", loc="left")
        ax.legend(loc="upper center", ncol=4, frameon=False)
        if index == len(manifest) - 1:
            ax.set_xlabel("Time (s)")

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "suite_dir": str(suite_dir),
        "output_path": str(output),
        "tasks": [entry["task"] for entry in manifest],
        "plotting_errors": plotting_errors,
    }
    (suite_dir / "suite_plot_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
