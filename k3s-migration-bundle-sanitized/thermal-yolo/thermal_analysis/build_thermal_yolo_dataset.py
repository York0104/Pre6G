#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import pandas as pd



def to_local_naive_datetime(x):
    """
    Normalize timestamps to local tz-naive datetime.

    Reason:
    - run_metadata.json uses date --iso-8601=seconds, usually tz-aware, e.g. +08:00
    - latency client timestamps are tz-naive local time
    - pandas cannot compare tz-aware and tz-naive timestamps directly

    This function drops timezone information while preserving local wall-clock time.
    """
    def _one(v):
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts):
            return pd.NaT
        if getattr(ts, "tzinfo", None) is not None:
            return ts.tz_localize(None)
        return ts

    if isinstance(x, pd.Series):
        return x.apply(_one)

    return _one(x)


def load_metadata(run_dir: Path):
    f = run_dir / "run_metadata.json"
    if not f.exists():
        raise FileNotFoundError(f"missing metadata: {f}")
    return json.loads(f.read_text())


def build_phase_schedule(meta):
    run_start = to_local_naive_datetime(meta["run_start_iso"])
    rows = []

    for p in meta["phase_plan"]:
        start = run_start + pd.Timedelta(seconds=float(p["offset_start_sec"]))
        end = run_start + pd.Timedelta(seconds=float(p["offset_end_sec"]))
        rows.append({
            "phase": p["phase"],
            "phase_start": start,
            "phase_end": end,
            "offset_start_sec": p["offset_start_sec"],
            "offset_end_sec": p["offset_end_sec"],
            "thermal_label": p["thermal_label"],
            "target_state": p["target_state"],
        })

    return pd.DataFrame(rows)


def assign_phase(ts, schedule):
    for _, r in schedule.iterrows():
        if ts >= r["phase_start"] and ts < r["phase_end"]:
            return r["phase"], r["thermal_label"], r["target_state"]
    return "outside_schedule", "unknown", "unknown"


def load_latency(run_dir: Path):
    f = run_dir / "outage_labeling" / "latency_3inst_outage_labeled.csv"
    if not f.exists():
        raise FileNotFoundError(f"missing outage-labeled latency file: {f}")

    df = pd.read_csv(f)
    df["ts"] = to_local_naive_datetime(df["ts"])
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    return df


def load_gpu_smi(run_dir: Path, worker_node: str):
    """
    Load GPU telemetry from metrics/gpu_smi_*.csv.

    This version also repairs malformed timestamp rows such as:
      2026-04-26T16:25:00,520912858+08:00,45,...
    which should be interpreted as:
      2026-04-26T16:25:00.520912858+08:00,45,...

    Root cause:
    GNU date / script output used comma as sub-second separator,
    but CSV also uses comma as delimiter.
    """
    metrics_dir = run_dir / "metrics"

    candidates = []
    preferred = metrics_dir / f"gpu_smi_{worker_node}.csv"

    if preferred.exists():
        candidates.append(preferred)

    candidates.extend(sorted(metrics_dir.glob("gpu_smi_*.csv")))

    seen = set()
    files = []
    for f in candidates:
        if f not in seen:
            files.append(f)
            seen.add(f)

    if not files:
        print(f"[WARN] no gpu_smi csv found under {metrics_dir}")
        return None

    chosen = None
    df = None

    for f in files:
        try:
            tmp = pd.read_csv(f)
            tmp.columns = [str(c).strip() for c in tmp.columns]

            if len(tmp) == 0:
                print(f"[WARN] skip empty gpu telemetry file: {f}")
                continue

            if "ts" not in tmp.columns:
                print(f"[WARN] skip gpu telemetry without ts column: {f}, columns={list(tmp.columns)}")
                continue

            # Repair malformed timestamp caused by comma inside timestamp.
            # Pandas usually treats the first timestamp part as index:
            # index = 2026-04-26T16:25:00
            # ts    = 520912858+08:00
            if not isinstance(tmp.index, pd.RangeIndex):
                repaired = tmp.reset_index()
                first_col = repaired.columns[0]

                ts_part = repaired["ts"].astype(str).str.strip()
                sec_part = repaired[first_col].astype(str).str.strip()

                # Detect rows like "520912858+08:00" or "520912858"
                mask = ts_part.str.match(r"^\d+([+-]\d\d:\d\d|Z)?$", na=False)

                if mask.mean() > 0.8:
                    repaired["ts"] = sec_part + "." + ts_part
                    repaired = repaired.drop(columns=[first_col])
                    tmp = repaired
                    print(f"[INFO] repaired comma-split timestamp in {f}")
                else:
                    tmp = repaired.rename(columns={first_col: "ts"})

            chosen = f
            df = tmp
            break

        except Exception as e:
            print(f"[WARN] failed to read gpu telemetry {f}: {e}")

    if df is None:
        print("[WARN] no valid gpu telemetry file loaded")
        return None

    print(f"[INFO] loaded gpu telemetry: {chosen}")

    df.columns = [str(c).strip() for c in df.columns]

    for c in df.columns:
        if df[c].dtype == "object":
            df[c] = df[c].astype(str).str.strip()

    df["ts"] = to_local_naive_datetime(df["ts"])
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)

    rename_map = {
        "temperature.gpu": "temperature_gpu_c",
        "power.draw": "power_draw_w",
        "utilization.gpu": "utilization_gpu_pct",
        "utilization.memory": "utilization_memory_pct",
        "memory.used": "memory_used_mib",
        "memory.total": "memory_total_mib",
        "clocks.sm": "clocks_sm_mhz",
        "clocks.mem": "clocks_mem_mhz",
        "fan.speed": "fan_speed_pct",
    }

    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    numeric_cols = [
        "temperature_gpu_c",
        "power_draw_w",
        "utilization_gpu_pct",
        "utilization_memory_pct",
        "memory_used_mib",
        "memory_total_mib",
        "clocks_sm_mhz",
        "clocks_mem_mhz",
        "fan_speed_pct",
    ]

    for c in numeric_cols:
        if c in df.columns:
            df[c] = (
                df[c]
                .astype(str)
                .str.replace("W", "", regex=False)
                .str.replace("MiB", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.strip()
            )
            df[c] = pd.to_numeric(df[c], errors="coerce")

    print("[INFO] gpu telemetry columns:", list(df.columns))
    print("[INFO] gpu telemetry rows:", len(df))

    if len(df) > 0:
        print("[INFO] gpu telemetry ts range:", df["ts"].min(), "~", df["ts"].max())

    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--merge-tolerance-sec", type=float, default=2.0)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    out_dir = run_dir / "dataset"
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = load_metadata(run_dir)
    schedule = build_phase_schedule(meta)
    latency = load_latency(run_dir)

    phase_info = latency["ts"].apply(lambda x: assign_phase(x, schedule))
    latency["thermal_phase"] = [x[0] for x in phase_info]
    latency["thermal_label"] = [x[1] for x in phase_info]
    latency["thermal_target_state"] = [x[2] for x in phase_info]

    latency["is_thermal_anomaly_phase"] = (latency["thermal_label"] == "thermal_anomaly").astype(int)
    latency["is_transition_phase"] = (latency["thermal_label"] == "transition").astype(int)

    # clean thermal training data:
    # 1. request success
    # 2. not service_unreachable
    # 3. not outage_buffer
    # 4. within phase schedule
    latency["use_for_thermal_performance_model"] = (
        (latency["success_bool"] == True) &
        (latency["service_state"] == "reachable") &
        (latency["thermal_label"].isin(["normal", "thermal_anomaly", "recovery", "transition"])) &
        (latency["latency_ms_client_num"].notna())
    ).astype(int)

    # QoS anomaly dataset keeps all rows, including failure.
    latency["use_for_thermal_qos_anomaly"] = 1

    gpu = load_gpu_smi(run_dir, meta["worker_node"])

    if gpu is not None and len(gpu) > 0:
        merged = pd.merge_asof(
            latency.sort_values("ts"),
            gpu.sort_values("ts"),
            on="ts",
            direction="nearest",
            tolerance=pd.Timedelta(seconds=args.merge_tolerance_sec),
        )
    else:
        merged = latency.copy()

    # Derive GPU memory used percentage if possible.
    if "memory_used_mib" in merged.columns and "memory_total_mib" in merged.columns:
        merged["gpu_memory_used_pct"] = (
            merged["memory_used_mib"] / merged["memory_total_mib"] * 100.0
        )

    out_labeled = out_dir / "thermal_yolo_labeled_dataset.csv"
    out_schedule = out_dir / "thermal_phase_schedule.csv"
    out_summary = out_dir / "thermal_yolo_dataset_summary.csv"

    merged.to_csv(out_labeled, index=False)
    schedule.to_csv(out_schedule, index=False)

    summary = (
        merged
        .groupby(["thermal_phase", "thermal_label", "availability_label", "sample_label"])
        .size()
        .reset_index(name="count")
        .sort_values(["thermal_phase", "availability_label", "sample_label"])
    )
    summary.to_csv(out_summary, index=False)

    print("wrote:", out_labeled)
    print("wrote:", out_schedule)
    print("wrote:", out_summary)
    print()
    print("=== phase schedule ===")
    print(schedule.to_string(index=False))
    print()
    print("=== summary ===")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
