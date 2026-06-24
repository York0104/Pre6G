#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


METRICS = [
    ("cpu_percent", "CPU", "#1f77b4", "-", 1.6, 2),
    ("ram_used_percent", "RAM", "#2ca02c", "--", 1.8, 3),
    ("gpu_util_percent", "GPU", "#ff7f0e", "-.", 1.6, 4),
    ("vram_used_percent", "VRAM", "#d62728", ":", 2.0, 5),
]

TASK_META = {
    "cpu_bound": {"panel": "(a)", "bound": "CPU-bound", "task": "Video Compression"},
    "ram_bound": {"panel": "(b)", "bound": "RAM-bound", "task": "Redis Stress"},
    "vram_bound": {"panel": "(c)", "bound": "VRAM-bound", "task": "Qwen3:32B"},
    "gpu_bound_experiment": {"panel": "(d)", "bound": "GPU-bound", "task": "YOLO26"},
}

PHASE_COLORS = {
    "warm-up": "#f2f2f2",
    "steady-state": "#dfeaf4",
    "cooldown": "#f7eadc",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Plot four-bound resource overview figure.")
    parser.add_argument("--cpu-run-dir", required=True)
    parser.add_argument("--ram-run-dir", required=True)
    parser.add_argument("--vram-run-dir", required=True)
    parser.add_argument("--gpu-run-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output", help="Optional JSON summary path")
    parser.add_argument("--smooth-window", type=int, default=1, help="Rolling median window size; 1 disables smoothing")
    return parser.parse_args()


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def load_config(path: Path):
    data = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    return data


def load_time_window(path: Path):
    data = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    return data


def load_phase_windows(path: Path):
    phases = []
    if not path.exists():
        return phases
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                start_s = float(row.get("start_s", ""))
                end_s = float(row.get("end_s", ""))
            except ValueError:
                continue
            phases.append({"phase": row.get("phase", "").strip(), "start_s": start_s, "end_s": end_s})
    return phases


def infer_phase_windows(run_dir: Path, task_name: str):
    phase_csv = run_dir / "phase_windows.csv"
    if phase_csv.exists():
        return load_phase_windows(phase_csv)

    cfg = load_config(run_dir / "experiment_config.txt")
    tw = load_time_window(run_dir / "time_window.txt")

    default_warmup = float(cfg.get("DEFAULT_WARMUP_SECONDS", "300") or 300)
    remote_end = tw.get("REMOTE_END_EPOCH")
    start = tw.get("START_EPOCH")
    end = tw.get("END_EPOCH")
    phases = []

    if start and end:
        start_epoch = float(start)
        end_epoch = float(end)
        warmup_end = default_warmup

        if remote_end:
            remote_elapsed = float(remote_end) - start_epoch
        else:
            remote_elapsed = end_epoch - start_epoch

        if task_name == "ram_bound":
            load_estimate = float(cfg.get("RAM_LOAD_ESTIMATE_SECONDS", "3000") or 3000)
            load_end = min(remote_elapsed, load_estimate)
            phases.append({"phase": "warm-up", "start_s": 0.0, "end_s": min(warmup_end, load_end)})
            if load_end > min(warmup_end, load_end):
                phases.append({"phase": "steady-state", "start_s": min(warmup_end, load_end), "end_s": load_end})
            if remote_elapsed > load_end:
                phases.append({"phase": "steady-state", "start_s": load_end, "end_s": remote_elapsed})
        else:
            phases.append({"phase": "warm-up", "start_s": 0.0, "end_s": min(warmup_end, remote_elapsed)})
            if remote_elapsed > warmup_end:
                phases.append({"phase": "steady-state", "start_s": warmup_end, "end_s": remote_elapsed})

        if end_epoch - start_epoch > remote_elapsed:
            phases.append({"phase": "cooldown", "start_s": remote_elapsed, "end_s": end_epoch - start_epoch})

    return phases


def load_monitor_csv(path: Path):
    rows = []
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


def rolling_median(values, window: int):
    if window <= 1:
        return values
    if window % 2 == 0:
        window += 1
    radius = window // 2
    smoothed = []
    for idx in range(len(values)):
        left = max(0, idx - radius)
        right = min(len(values), idx + radius + 1)
        chunk = sorted(values[left:right])
        smoothed.append(chunk[len(chunk) // 2])
    return smoothed


def plot_task(ax, rows, task_name: str, phase_windows, smooth_window: int, show_legend=False):
    for phase in phase_windows:
        color = PHASE_COLORS.get(phase["phase"])
        if not color:
            continue
        ax.axvspan(phase["start_s"], phase["end_s"], color=color, alpha=0.8, zorder=0)

    for key, label, color, linestyle, linewidth, zorder in METRICS:
        x = [row["elapsed_s"] for row in rows if row.get(key) is not None]
        y = [row[key] for row in rows if row.get(key) is not None]
        if not x:
            continue
        y = rolling_median(y, smooth_window)
        ax.plot(x, y, color=color, linestyle=linestyle, linewidth=linewidth, label=label, zorder=zorder)

    meta = TASK_META.get(task_name, {"panel": "", "bound": task_name, "task": ""})
    if meta.get("task"):
        title = f"{meta['panel']} {meta['bound']}: {meta['task']}".strip()
    else:
        title = f"{meta['panel']} {meta['bound']}".strip()
    ax.set_title(title, loc="left")
    ax.set_ylim(0, 100)
    ax.set_ylabel("Util. (%)")
    ax.grid(True, axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if show_legend:
        ax.legend(loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.18))


def main():
    args = parse_args()
    run_map = {
        "cpu_bound": resolve_path(args.cpu_run_dir),
        "ram_bound": resolve_path(args.ram_run_dir),
        "vram_bound": resolve_path(args.vram_run_dir),
        "gpu_bound_experiment": resolve_path(args.gpu_run_dir),
    }
    output_path = resolve_path(args.output)
    summary_output = resolve_path(args.summary_output) if args.summary_output else output_path.with_suffix(".summary.json")

    fig, axes = plt.subplots(4, 1, figsize=(14, 14), constrained_layout=True, sharex=False)

    summary = {"output_path": str(output_path), "runs": {}}

    for index, (task_name, run_dir) in enumerate(run_map.items()):
        rows = load_monitor_csv(run_dir / "combined_monitor.csv")
        phases = infer_phase_windows(run_dir, task_name)
        plot_task(axes[index], rows, task_name, phases, smooth_window=args.smooth_window, show_legend=(index == 0))
        if index == len(run_map) - 1:
            axes[index].set_xlabel("Time (s)")
        summary["runs"][task_name] = {
            "run_dir": str(run_dir),
            "combined_monitor_csv": str(run_dir / "combined_monitor.csv"),
            "phase_windows": phases,
            "rows": len(rows),
        }
    summary["smooth_window"] = args.smooth_window

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)

    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
