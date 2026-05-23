#!/usr/bin/env python3
import json
import sys
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def find_deployment(metrics: dict, name: str):
    for dep in metrics.get("cluster_semantic", {}).get("deployments", []):
        if dep.get("name") == name:
            return dep
    return None


def mib_gib(bytes_val):
    if bytes_val is None:
        return None
    return bytes_val / (1024 ** 3)


def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            obj = json.loads(line)

            metrics = obj.get("metrics")
            if not metrics:
                continue

            stress = obj.get("stress_phase", {})
            sample_time = obj.get("sample_time")

            cluster = metrics.get("cluster_semantic", {})
            target = metrics.get("target_node_semantic", {})

            ns_total = cluster.get("namespace_total", {})
            node_inst = target.get("node_pressure_instant", {})

            dep_hello = find_deployment(metrics, "hello")
            dep_worker = find_deployment(metrics, "test-worker-icclz1")

            row = {
                "sample_time": sample_time,
                "phase_name": stress.get("phase_name"),
                "load_percent": stress.get("load_percent"),

                "namespace_cpu_cores_rate": ns_total.get("cpu_cores_rate"),
                "namespace_memory_gib": mib_gib(ns_total.get("memory_working_set_bytes")),

                "node_cpu_usage_percent": node_inst.get("cpu_usage_percent"),
                "node_cpu_cores": node_inst.get("node_cpu_cores"),
                "node_memory_usage_percent": node_inst.get("memory_usage_percent"),
                "node_memory_gib": mib_gib(node_inst.get("node_memory_working_set_bytes")),
            }

            if dep_hello:
                row["hello_cpu_cores_rate"] = dep_hello.get("cpu_cores_rate")
                row["hello_memory_gib"] = mib_gib(dep_hello.get("memory_working_set_bytes"))
            else:
                row["hello_cpu_cores_rate"] = None
                row["hello_memory_gib"] = None

            if dep_worker:
                row["worker_cpu_cores_rate"] = dep_worker.get("cpu_cores_rate")
                row["worker_memory_gib"] = mib_gib(dep_worker.get("memory_working_set_bytes"))
            else:
                row["worker_cpu_cores_rate"] = None
                row["worker_memory_gib"] = None

            rows.append(row)

    df = pd.DataFrame(rows)
    df["sample_time"] = pd.to_datetime(df["sample_time"])
    return df


def save_csv(df: pd.DataFrame, out_csv: Path):
    df.to_csv(out_csv, index=False)
    print(f"[INFO] CSV written to {out_csv}")


def plot_series(df: pd.DataFrame, x: str, y: str, title: str, out_png: Path):
    plt.figure(figsize=(12, 4))
    plt.plot(df[x], df[y])
    plt.title(title)
    plt.xlabel("time")
    plt.ylabel(y)
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()
    print(f"[INFO] plot written to {out_png}")


def plot_dual_axis(df: pd.DataFrame, x: str, y_left: str, y_right: str,
                   title: str, out_png: Path,
                   y_left_label: str = None, y_right_label: str = None):
    fig, ax1 = plt.subplots(figsize=(12, 4))

    ax1.plot(df[x], df[y_left])
    ax1.set_title(title)
    ax1.set_xlabel("time")
    ax1.set_ylabel(y_left_label or y_left)

    ax2 = ax1.twinx()
    ax2.plot(df[x], df[y_right], linestyle="--")
    ax2.set_ylabel(y_right_label or y_right)

    plt.xticks(rotation=30)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    print(f"[INFO] dual-axis plot written to {out_png}")


def build_grouped_mean(df: pd.DataFrame, value_cols: list[str]) -> pd.DataFrame:
    grouped = (
        df.groupby("load_percent", dropna=True)[value_cols]
        .mean(numeric_only=True)
        .reset_index()
        .sort_values("load_percent")
    )
    return grouped


def plot_grouped_bar(grouped_df: pd.DataFrame, x: str, y: str,
                     title: str, out_png: Path):
    plt.figure(figsize=(10, 4))
    plt.bar(grouped_df[x].astype(str), grouped_df[y])
    plt.title(title)
    plt.xlabel(x)
    plt.ylabel(y)
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()
    print(f"[INFO] grouped bar plot written to {out_png}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/plot_stress_trends.py <jsonl_file>")
        sys.exit(1)

    in_file = Path(sys.argv[1]).resolve()
    out_dir = in_file.parent / (in_file.stem + "_plots")
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_jsonl(in_file)

    save_csv(df, out_dir / "flattened_metrics.csv")

    plot_series(df, "sample_time", "load_percent", "Stress Load Percent", out_dir / "01_load_percent.png")
    plot_series(df, "sample_time", "namespace_cpu_cores_rate", "Namespace CPU Cores Rate", out_dir / "02_namespace_cpu.png")
    plot_series(df, "sample_time", "namespace_memory_gib", "Namespace Memory Working Set (GiB)", out_dir / "03_namespace_memory.png")
    plot_series(df, "sample_time", "hello_cpu_cores_rate", "Hello Deployment CPU Cores Rate", out_dir / "04_hello_cpu.png")
    plot_series(df, "sample_time", "hello_memory_gib", "Hello Deployment Memory (GiB)", out_dir / "05_hello_memory.png")
    plot_series(df, "sample_time", "worker_cpu_cores_rate", "Worker Deployment CPU Cores Rate", out_dir / "06_worker_cpu.png")
    plot_series(df, "sample_time", "worker_memory_gib", "Worker Deployment Memory (GiB)", out_dir / "07_worker_memory.png")
    plot_series(df, "sample_time", "node_cpu_usage_percent", "Node CPU Usage Percent", out_dir / "08_node_cpu_percent.png")
    plot_series(df, "sample_time", "node_memory_usage_percent", "Node Memory Usage Percent", out_dir / "09_node_memory_percent.png")

    plot_dual_axis(df, "sample_time", "namespace_cpu_cores_rate", "load_percent",
                   "Namespace CPU vs Load Percent", out_dir / "10_namespace_cpu_vs_load.png",
                   "namespace cpu cores rate", "load percent")
    plot_dual_axis(df, "sample_time", "namespace_memory_gib", "load_percent",
                   "Namespace Memory vs Load Percent", out_dir / "11_namespace_memory_vs_load.png",
                   "namespace memory (GiB)", "load percent")
    plot_dual_axis(df, "sample_time", "hello_cpu_cores_rate", "load_percent",
                   "Hello CPU vs Load Percent", out_dir / "12_hello_cpu_vs_load.png",
                   "hello cpu cores rate", "load percent")
    plot_dual_axis(df, "sample_time", "hello_memory_gib", "load_percent",
                   "Hello Memory vs Load Percent", out_dir / "13_hello_memory_vs_load.png",
                   "hello memory (GiB)", "load percent")
    plot_dual_axis(df, "sample_time", "worker_cpu_cores_rate", "load_percent",
                   "Worker CPU vs Load Percent", out_dir / "14_worker_cpu_vs_load.png",
                   "worker cpu cores rate", "load percent")
    plot_dual_axis(df, "sample_time", "worker_memory_gib", "load_percent",
                   "Worker Memory vs Load Percent", out_dir / "15_worker_memory_vs_load.png",
                   "worker memory (GiB)", "load percent")
    plot_dual_axis(df, "sample_time", "node_cpu_usage_percent", "load_percent",
                   "Node CPU Usage vs Load Percent", out_dir / "16_node_cpu_vs_load.png",
                   "node cpu usage percent", "load percent")
    plot_dual_axis(df, "sample_time", "node_memory_usage_percent", "load_percent",
                   "Node Memory Usage vs Load Percent", out_dir / "17_node_memory_vs_load.png",
                   "node memory usage percent", "load percent")

    value_cols = [
        "namespace_cpu_cores_rate",
        "namespace_memory_gib",
        "hello_cpu_cores_rate",
        "hello_memory_gib",
        "worker_cpu_cores_rate",
        "worker_memory_gib",
        "node_cpu_usage_percent",
        "node_memory_usage_percent",
    ]

    grouped_mean = build_grouped_mean(df, value_cols)
    grouped_mean.to_csv(out_dir / "grouped_mean_by_load.csv", index=False)
    print(f"[INFO] grouped mean csv written to {out_dir / 'grouped_mean_by_load.csv'}")

    plot_grouped_bar(grouped_mean, "load_percent", "namespace_cpu_cores_rate",
                     "Grouped Mean: Namespace CPU by Load", out_dir / "18_grouped_namespace_cpu.png")
    plot_grouped_bar(grouped_mean, "load_percent", "namespace_memory_gib",
                     "Grouped Mean: Namespace Memory by Load", out_dir / "19_grouped_namespace_memory.png")
    plot_grouped_bar(grouped_mean, "load_percent", "hello_cpu_cores_rate",
                     "Grouped Mean: Hello CPU by Load", out_dir / "20_grouped_hello_cpu.png")
    plot_grouped_bar(grouped_mean, "load_percent", "hello_memory_gib",
                     "Grouped Mean: Hello Memory by Load", out_dir / "21_grouped_hello_memory.png")
    plot_grouped_bar(grouped_mean, "load_percent", "worker_cpu_cores_rate",
                     "Grouped Mean: Worker CPU by Load", out_dir / "22_grouped_worker_cpu.png")
    plot_grouped_bar(grouped_mean, "load_percent", "worker_memory_gib",
                     "Grouped Mean: Worker Memory by Load", out_dir / "23_grouped_worker_memory.png")
    plot_grouped_bar(grouped_mean, "load_percent", "node_cpu_usage_percent",
                     "Grouped Mean: Node CPU by Load", out_dir / "24_grouped_node_cpu.png")
    plot_grouped_bar(grouped_mean, "load_percent", "node_memory_usage_percent",
                     "Grouped Mean: Node Memory by Load", out_dir / "25_grouped_node_memory.png")


if __name__ == "__main__":
    main()