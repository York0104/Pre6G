#!/usr/bin/env python3
import argparse
from pathlib import Path

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--vmagg-csv", default="")
    ap.add_argument("--tolerance-sec", type=float, default=5.0)
    args = ap.parse_args()

    run_dir = Path(args.run_dir).expanduser()

    dataset_path = run_dir / "dataset" / "thermal_yolo_labeled_dataset.csv"
    if args.vmagg_csv:
        vmagg_path = Path(args.vmagg_csv).expanduser()
    else:
        files = sorted((run_dir / "metrics").glob("vm_aggregator_*.csv"))
        if not files:
            raise FileNotFoundError(f"No vm_aggregator_*.csv found under {run_dir / 'metrics'}")
        vmagg_path = files[0]

    out_path = run_dir / "dataset" / "thermal_yolo_labeled_dataset_with_vmagg.csv"

    df = pd.read_csv(dataset_path)
    vm = pd.read_csv(vmagg_path)

    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    vm["ts"] = pd.to_datetime(vm["ts"], errors="coerce")

    df = df.dropna(subset=["ts"]).sort_values("ts")
    vm = vm.dropna(subset=["ts"]).sort_values("ts")

    merged = pd.merge_asof(
        df,
        vm,
        on="ts",
        direction="nearest",
        tolerance=pd.Timedelta(seconds=args.tolerance_sec),
        suffixes=("", "_vmagg"),
    )

    merged.to_csv(out_path, index=False)

    print("[OK] merged dataset")
    print("dataset =", dataset_path)
    print("vmagg   =", vmagg_path)
    print("out     =", out_path)
    print("rows    =", len(merged))
    print("cols    =", len(merged.columns))
    if "collector_ok" in merged.columns:
        print("vmagg matched ratio =", merged["collector_ok"].notna().mean())


if __name__ == "__main__":
    main()
