#!/usr/bin/env python3
#plot_thermal_yolo_dataset.py

import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()

    run_dir = Path(args.run_dir).expanduser()
    dataset_path = run_dir / "dataset" / "thermal_yolo_labeled_dataset.csv"
    out_dir = run_dir / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(dataset_path)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    df = df.dropna(subset=["ts"]).sort_values("ts")

    if "latency_ms_client_num" not in df.columns and "latency_ms_client" in df.columns:
        df["latency_ms_client_num"] = pd.to_numeric(df["latency_ms_client"], errors="coerce")

    ok = df[df.get("success_bool", True) == True].copy()
    if "latency_ms_client_num" in ok.columns:
        ok["latency_ms_client_num"] = pd.to_numeric(ok["latency_ms_client_num"], errors="coerce")

    # 1. Temperature time series
    if "temperature_gpu_c" in df.columns:
        plt.figure(figsize=(14, 5))
        plt.plot(df["ts"], df["temperature_gpu_c"])
        plt.xlabel("Time")
        plt.ylabel("GPU Temperature (C)")
        plt.title("GPU Temperature Over Time")
        plt.xticks(rotation=30)
        plt.tight_layout()
        plt.savefig(out_dir / "gpu_temperature_timeseries.png", dpi=150)
        plt.close()

    # 2. Power time series
    if "power_draw_w" in df.columns:
        plt.figure(figsize=(14, 5))
        plt.plot(df["ts"], df["power_draw_w"])
        plt.xlabel("Time")
        plt.ylabel("GPU Power Draw (W)")
        plt.title("GPU Power Draw Over Time")
        plt.xticks(rotation=30)
        plt.tight_layout()
        plt.savefig(out_dir / "gpu_power_timeseries.png", dpi=150)
        plt.close()

    # 3. Client latency time series
    if "latency_ms_client_num" in ok.columns:
        plt.figure(figsize=(14, 5))
        plt.plot(ok["ts"], ok["latency_ms_client_num"], marker=".", linestyle="none", markersize=2)
        plt.xlabel("Time")
        plt.ylabel("Client Latency (ms)")
        plt.title("YOLO Client Latency Over Time")
        plt.xticks(rotation=30)
        plt.tight_layout()
        plt.savefig(out_dir / "client_latency_timeseries.png", dpi=150)
        plt.close()

    # 4. SM clock time series
    if "clocks_sm_mhz" in df.columns:
        plt.figure(figsize=(14, 5))
        plt.plot(df["ts"], df["clocks_sm_mhz"])
        plt.xlabel("Time")
        plt.ylabel("SM Clock (MHz)")
        plt.title("GPU SM Clock Over Time")
        plt.xticks(rotation=30)
        plt.tight_layout()
        plt.savefig(out_dir / "sm_clock_timeseries.png", dpi=150)
        plt.close()

    # 5. Latency by phase boxplot
    if "thermal_phase" in ok.columns and "latency_ms_client_num" in ok.columns:
        phases = [
            "pre_normal",
            "ramp_up",
            "high_temp_hold",
            "ramp_down",
            "post_normal",
        ]
        data = []
        labels = []
        for ph in phases:
            vals = ok.loc[ok["thermal_phase"] == ph, "latency_ms_client_num"].dropna()
            if len(vals) > 0:
                data.append(vals)
                labels.append(ph)

        if data:
            plt.figure(figsize=(12, 5))
            plt.boxplot(data, labels=labels, showfliers=False)
            plt.xlabel("Thermal Phase")
            plt.ylabel("Client Latency (ms)")
            plt.title("YOLO Client Latency by Thermal Phase")
            plt.xticks(rotation=20)
            plt.tight_layout()
            plt.savefig(out_dir / "client_latency_by_phase_boxplot.png", dpi=150)
            plt.close()

    # 6. Failure count by phase
    if "thermal_phase" in df.columns and "success_bool" in df.columns:
        fail = df[df["success_bool"] == False]
        if len(fail) > 0:
            count = fail.groupby("thermal_phase").size()
            plt.figure(figsize=(10, 5))
            plt.bar(count.index.astype(str), count.values)
            plt.xlabel("Thermal Phase")
            plt.ylabel("Failed Requests")
            plt.title("Failed Requests by Thermal Phase")
            plt.xticks(rotation=20)
            plt.tight_layout()
            plt.savefig(out_dir / "failed_requests_by_phase.png", dpi=150)
            plt.close()

    # 7. Summary table
    summary = []

    if "thermal_phase" in df.columns:
        for ph, g in df.groupby("thermal_phase"):
            row = {"thermal_phase": ph, "rows": len(g)}
            if "temperature_gpu_c" in g.columns:
                row["temp_mean"] = g["temperature_gpu_c"].mean()
                row["temp_max"] = g["temperature_gpu_c"].max()
            if "power_draw_w" in g.columns:
                row["power_mean"] = g["power_draw_w"].mean()
            if "latency_ms_client_num" in g.columns:
                gg = g[g.get("success_bool", True) == True]
                row["lat_p50"] = gg["latency_ms_client_num"].quantile(0.50)
                row["lat_p95"] = gg["latency_ms_client_num"].quantile(0.95)
                row["lat_p99"] = gg["latency_ms_client_num"].quantile(0.99)
            if "success_bool" in g.columns:
                row["success_rate"] = g["success_bool"].mean()
            summary.append(row)

    if summary:
        pd.DataFrame(summary).to_csv(out_dir / "plot_summary_by_phase.csv", index=False)

    print(f"[OK] wrote plots to: {out_dir}")


if __name__ == "__main__":
    main()