#!/usr/bin/env python3
import argparse
import glob
from pathlib import Path

import pandas as pd


def infer_cycle_index(run_id: str):
    import re
    m = re.search(r"cycle(\d+)", run_id)
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-glob", action="append", default=[])
    ap.add_argument("--run-dir", action="append", default=[])
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    run_dirs = []

    for g in args.run_glob:
        run_dirs.extend(glob.glob(str(Path(g).expanduser())))

    for d in args.run_dir:
        run_dirs.append(str(Path(d).expanduser()))

    run_dirs = sorted(set(run_dirs))

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    manifest = []

    for rd in run_dirs:
        run_dir = Path(rd).expanduser()
        run_id = run_dir.name
        f = run_dir / "dataset" / "thermal_yolo_labeled_dataset.csv"

        if not f.exists():
            print(f"[WARN] skip, dataset not found: {f}")
            continue

        df = pd.read_csv(f)
        df["run_id"] = run_id
        df["cycle_index"] = infer_cycle_index(run_id)

        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], errors="coerce")

        frames.append(df)

        manifest.append({
            "run_id": run_id,
            "run_dir": str(run_dir),
            "rows": len(df),
            "ts_min": df["ts"].min() if "ts" in df.columns else None,
            "ts_max": df["ts"].max() if "ts" in df.columns else None,
        })

        print(f"[OK] loaded {run_id}: rows={len(df)}")

    if not frames:
        raise SystemExit("[ERROR] no valid datasets loaded")

    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.sort_values(["run_id", "ts"], na_position="last")

    out_dataset = out_dir / "all_cycles_thermal_yolo_dataset.csv"
    out_manifest = out_dir / "run_manifest.csv"
    out_summary = out_dir / "summary_by_run_phase_label.csv"

    all_df.to_csv(out_dataset, index=False)
    pd.DataFrame(manifest).to_csv(out_manifest, index=False)

    group_cols = []
    for c in ["run_id", "cycle_index", "thermal_phase", "thermal_label", "availability_label", "sample_label"]:
        if c in all_df.columns:
            group_cols.append(c)

    summary = all_df.groupby(group_cols).size().reset_index(name="count")
    summary.to_csv(out_summary, index=False)

    print()
    print("[DONE]")
    print("dataset:", out_dataset)
    print("manifest:", out_manifest)
    print("summary:", out_summary)
    print("total rows:", len(all_df))
    print()
    print("sample_label counts:")
    if "sample_label" in all_df.columns:
        print(all_df["sample_label"].value_counts(dropna=False))


if __name__ == "__main__":
    main()
