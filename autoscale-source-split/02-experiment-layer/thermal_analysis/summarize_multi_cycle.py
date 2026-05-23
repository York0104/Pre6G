#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path

def read_service_summary(csv_path: Path):
    rows = {}
    if not csv_path.exists():
        return rows
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows[r["phase"]] = r
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-dir", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    batch_dir = Path(args.batch_dir)
    out_csv = Path(args.out) if args.out else batch_dir / "batch_summary.csv"
    manifest_csv = batch_dir / "batch_manifest.csv"

    if not manifest_csv.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_csv}")

    fieldnames = [
        "cycle_idx",
        "run_id",
        "status",
        "within_band_ratio",
        "avg_gpu_temp_all",
        "avg_gpu_temp_within_band",
        "avg_gpu_power_all",
        "avg_gpu_util_all",
        "warmup_client_mean",
        "normal_client_mean",
        "fault_ramp_up_client_mean",
        "fault_hold_client_mean",
        "warmup_client_p95",
        "normal_client_p95",
        "fault_ramp_up_client_p95",
        "fault_hold_client_p95",
        "warmup_server_mean",
        "normal_server_mean",
        "fault_ramp_up_server_mean",
        "fault_hold_server_mean",
    ]

    with open(manifest_csv, newline="", encoding="utf-8") as mf, open(
        out_csv, "w", newline="", encoding="utf-8"
    ) as of:
        manifest_reader = csv.DictReader(mf)
        writer = csv.DictWriter(of, fieldnames=fieldnames)
        writer.writeheader()

        for m in manifest_reader:
            run_dir = Path(m["run_dir"])
            status = m.get("status", "")

            if status != "ok":
                continue

            aligned_summary = run_dir / "aligned_summary.json"
            service_summary = run_dir / "service_latency_summary.csv"

            if not aligned_summary.exists():
                continue

            with open(aligned_summary, "r", encoding="utf-8") as jf:
                js = json.load(jf)

            svc = read_service_summary(service_summary)

            row = {
                "cycle_idx": m.get("cycle_idx"),
                "run_id": run_dir.name,
                "status": status,
                "within_band_ratio": js.get("within_band_ratio"),
                "avg_gpu_temp_all": js.get("avg_gpu_temp_all"),
                "avg_gpu_temp_within_band": js.get("avg_gpu_temp_within_band"),
                "avg_gpu_power_all": js.get("avg_gpu_power_all"),
                "avg_gpu_util_all": js.get("avg_gpu_util_all"),
                "warmup_client_mean": svc.get("warmup", {}).get("client_mean"),
                "normal_client_mean": svc.get("normal_hold", {}).get("client_mean"),
                "fault_ramp_up_client_mean": svc.get("fault_ramp_up", {}).get("client_mean"),
                "fault_hold_client_mean": svc.get("fault_hold", {}).get("client_mean"),
                "warmup_client_p95": svc.get("warmup", {}).get("client_p95"),
                "normal_client_p95": svc.get("normal_hold", {}).get("client_p95"),
                "fault_ramp_up_client_p95": svc.get("fault_ramp_up", {}).get("client_p95"),
                "fault_hold_client_p95": svc.get("fault_hold", {}).get("client_p95"),
                "warmup_server_mean": svc.get("warmup", {}).get("server_mean"),
                "normal_server_mean": svc.get("normal_hold", {}).get("server_mean"),
                "fault_ramp_up_server_mean": svc.get("fault_ramp_up", {}).get("server_mean"),
                "fault_hold_server_mean": svc.get("fault_hold", {}).get("server_mean"),
            }
            writer.writerow(row)

    print(f"written: {out_csv}")

if __name__ == "__main__":
    main()
