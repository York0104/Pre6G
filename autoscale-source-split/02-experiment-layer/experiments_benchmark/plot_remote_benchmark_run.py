#!/usr/bin/env python3
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


TASK_LABELS = {
    "cpu_bound": "CPU-bound Video Compression",
    "ram_bound": "RAM-bound Redis Stress",
    "vram_bound": "VRAM-bound Qwen3:32B",
    "gpu_bound_experiment": "GPU-bound YOLO Burn",
}

METRICS = [
    ("cpu_percent", "CPU", "#1f77b4", "-", 1.6, 2),
    ("ram_used_percent", "RAM", "#2ca02c", "--", 1.8, 3),
    ("gpu_util_percent", "GPU", "#ff7f0e", "-.", 1.4, 4),
    ("vram_used_percent", "VRAM", "#b22222", ":", 2.2, 5),
]


def parse_args():
    parser = argparse.ArgumentParser(description="Plot CPU/RAM/GPU/VRAM metrics for a remote benchmark run.")
    parser.add_argument("--run-dir", required=True, help="Run directory under experiments_benchmark/results")
    parser.add_argument("--output", help="Optional output image path")
    return parser.parse_args()


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def parse_float(text: str | None):
    if text is None:
        return None
    value = text.strip()
    if not value:
        return None
    for suffix in ("%", "MiB", "GiB", "W", "MHz"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        return None


def parse_time_window(path: Path):
    start_epoch = None
    end_epoch = None
    if not path.exists():
        return start_epoch, end_epoch
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("START_EPOCH="):
            start_epoch = float(line.split("=", 1)[1])
        elif line.startswith("END_EPOCH="):
            end_epoch = float(line.split("=", 1)[1])
    return start_epoch, end_epoch


def parse_kubectl_top(path: Path):
    samples = []
    if not path.exists():
        return samples

    current_ts = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("timestamp,"):
            iso = line.split(",", 1)[1]
            try:
                current_ts = datetime.fromisoformat(iso).timestamp()
            except ValueError:
                current_ts = None
            continue
        if line.startswith("[") or line == "----":
            continue
        parts = line.split()
        if len(parts) < 5 or current_ts is None:
            continue
        cpu_percent = parse_float(parts[2])
        ram_percent = parse_float(parts[4])
        if cpu_percent is None and ram_percent is None:
            continue
        samples.append(
            {
                "timestamp": current_ts,
                "cpu_percent": cpu_percent,
                "ram_used_percent": ram_percent,
            }
        )
    return samples


def parse_vm_aggregator(path: Path):
    samples = []
    if not path.exists():
        return samples

    cpu_keys = [
        "vmagg.target_node_semantic.node_compute_features.cpu_compute.cpu_usage_percent",
        "vmagg.target_node_semantic.node_pressure_instant.cpu_usage_percent",
        "vmagg._debug.netdata_node_cpu_used_percent",
    ]
    ram_keys = [
        "vmagg.target_node_semantic.node_compute_features.ram_capacity.memory_usage_percent",
        "vmagg.target_node_semantic.node_pressure_instant.memory_usage_percent",
        "vmagg._debug.netdata_node_mem_used_percent",
    ]

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ts_text = row.get("ts", "").strip()
            if not ts_text:
                continue
            try:
                timestamp = datetime.fromisoformat(ts_text).timestamp()
            except ValueError:
                continue

            cpu_percent = None
            ram_percent = None
            for key in cpu_keys:
                cpu_percent = parse_float(row.get(key))
                if cpu_percent is not None:
                    break
            for key in ram_keys:
                ram_percent = parse_float(row.get(key))
                if ram_percent is not None:
                    break

            if cpu_percent is None and ram_percent is None:
                continue

            samples.append(
                {
                    "timestamp": timestamp,
                    "cpu_percent": cpu_percent,
                    "ram_used_percent": ram_percent,
                }
            )
    return samples


def parse_nvidia_smi_timestamp(text: str):
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text.strip(), fmt).timestamp()
        except ValueError:
            continue
    return None


def parse_nvidia_smi(path: Path):
    samples = []
    if not path.exists():
        return samples
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row or row[0].startswith("timestamp"):
                continue
            if len(row) < 7:
                continue
            ts = parse_nvidia_smi_timestamp(row[0])
            gpu_util = parse_float(row[3])
            memory_used = parse_float(row[5])
            memory_total = parse_float(row[6])
            vram_percent = None
            if memory_used is not None and memory_total not in (None, 0):
                vram_percent = (memory_used / memory_total) * 100.0
            if ts is None and samples:
                ts = samples[-1]["timestamp"] + 1.0
            elif ts is None:
                ts = 0.0
            samples.append(
                {
                    "timestamp": ts,
                    "gpu_util_percent": gpu_util,
                    "vram_used_percent": vram_percent,
                }
            )
    return samples


def merge_samples(cpu_ram_samples, gpu_vram_samples, start_epoch):
    merged = []

    def build_row(sample, source):
        timestamp = sample["timestamp"]
        row = {
            "timestamp": timestamp,
            "elapsed_s": (timestamp - start_epoch) if start_epoch is not None else float(len(merged)),
            "cpu_percent": None,
            "ram_used_percent": None,
            "gpu_util_percent": None,
            "vram_used_percent": None,
        }
        if source == "cpu_ram":
            row["cpu_percent"] = sample.get("cpu_percent")
            row["ram_used_percent"] = sample.get("ram_used_percent")
        else:
            row["gpu_util_percent"] = sample.get("gpu_util_percent")
            row["vram_used_percent"] = sample.get("vram_used_percent")
        return row

    rows = [build_row(sample, "cpu_ram") for sample in cpu_ram_samples]
    rows.extend(build_row(sample, "gpu_vram") for sample in gpu_vram_samples)
    rows.sort(key=lambda item: item["timestamp"])

    last_values = {
        "cpu_percent": None,
        "ram_used_percent": None,
        "gpu_util_percent": None,
        "vram_used_percent": None,
    }
    for row in rows:
        for key in list(last_values):
            if row[key] is None:
                row[key] = last_values[key]
            else:
                last_values[key] = row[key]
        merged.append(row)
    return merged


def write_monitor_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "elapsed_s", "cpu_percent", "ram_used_percent", "gpu_util_percent", "vram_used_percent"],
        )
        writer.writeheader()
        writer.writerows(rows)


def load_experiment_config(path: Path):
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
    if not path.exists():
        return []
    phases = []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                start_s = float(row.get("start_s", ""))
                end_s = float(row.get("end_s", ""))
            except ValueError:
                continue
            phases.append(
                {
                    "phase": row.get("phase", "").strip(),
                    "start_s": start_s,
                    "end_s": end_s,
                }
            )
    return phases


def plot_run(rows, task_name: str, output_path: Path, phase_windows=None):
    fig, ax = plt.subplots(figsize=(12, 4.8), constrained_layout=True)
    phase_windows = phase_windows or []
    phase_colors = {
        "warm-up": "#dbeafe",
        "steady-state": "#e8f5e9",
        "cooldown": "#fff3e0",
    }

    for phase in phase_windows:
        phase_name = phase.get("phase", "")
        color = phase_colors.get(phase_name)
        if not color:
            continue
        ax.axvspan(phase["start_s"], phase["end_s"], color=color, alpha=0.35, zorder=0)

    for key, label, color, linestyle, linewidth, zorder in METRICS:
        x = [row["elapsed_s"] for row in rows if row.get(key) is not None]
        y = [row[key] for row in rows if row.get(key) is not None]
        if not x:
            continue
        ax.plot(x, y, color=color, linestyle=linestyle, linewidth=linewidth, label=label, zorder=zorder)

    ax.set_ylim(0, 100)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Util. (%)")
    ax.grid(True, axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(loc="upper center", ncol=4, frameon=False)
    ax.set_title(TASK_LABELS.get(task_name, task_name))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main():
    args = parse_args()
    run_dir = resolve_path(args.run_dir)
    time_window = run_dir / "time_window.txt"
    config_path = run_dir / "experiment_config.txt"
    task_name = load_experiment_config(config_path).get("TASK", run_dir.name)
    output_path = resolve_path(args.output) if args.output else run_dir / "resource_utilization.png"

    start_epoch, _ = parse_time_window(time_window)
    cpu_ram_samples = parse_kubectl_top(run_dir / "kubectl_top_node_1s.log")
    cpu_ram_source = "kubectl_top_node_1s.log"
    if not cpu_ram_samples:
        cpu_ram_samples = parse_vm_aggregator(run_dir / "vm_aggregator_timeseries.csv")
        if cpu_ram_samples:
            cpu_ram_source = "vm_aggregator_timeseries.csv"
    gpu_vram_samples = parse_nvidia_smi(run_dir / "worker_nvidia_smi_1s.csv")

    rows = merge_samples(cpu_ram_samples, gpu_vram_samples, start_epoch)
    if not rows:
        raise SystemExit(f"No monitor samples found in {run_dir}")

    phase_windows = load_phase_windows(run_dir / "phase_windows.csv")
    write_monitor_csv(run_dir / "combined_monitor.csv", rows)
    plot_run(rows, task_name, output_path, phase_windows=phase_windows)

    summary = {
        "run_dir": str(run_dir),
        "task_name": task_name,
        "output_path": str(output_path),
        "rows": len(rows),
        "sources": {
            "cpu_ram_source": cpu_ram_source if cpu_ram_samples else "",
            "kubectl_top_node_1s.log": (run_dir / "kubectl_top_node_1s.log").exists(),
            "vm_aggregator_timeseries.csv": (run_dir / "vm_aggregator_timeseries.csv").exists(),
            "worker_nvidia_smi_1s.csv": (run_dir / "worker_nvidia_smi_1s.csv").exists(),
        },
    }
    (run_dir / "plot_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
