#!/usr/bin/env python3
import argparse
from pathlib import Path
import pandas as pd


DEFAULT_FILES = [
    ("focus", "yolo26n-focus", "focus_inst1.csv"),
    ("focus", "yolo26n-focus", "raw_latency/focus_inst1_raw.csv"),
    ("background", "yolo26n-bg-1", "bg_inst2.csv"),
    ("background", "yolo26n-bg-1", "raw_latency/bg_inst2_raw.csv"),
    ("background", "yolo26n-bg-2", "bg_inst3.csv"),
    ("background", "yolo26n-bg-2", "raw_latency/bg_inst3_raw.csv"),
]


def parse_success(x):
    s = str(x).strip().lower()
    return s in ["1", "true", "yes", "ok"]


def classify_failure(status_code, error_msg):
    msg = str(error_msg).lower()

    try:
        code = int(status_code)
    except Exception:
        code = 0

    if 200 <= code < 300:
        return "none"

    if code == 0:
        if "connecttimeout" in msg or "connect timeout" in msg:
            return "connect_timeout"
        if "readtimeout" in msg or "read timeout" in msg or "timed out" in msg or "timeout" in msg:
            return "read_timeout"
        if "remote disconnected" in msg:
            return "remote_disconnected"
        if "connectionerror" in msg or "connection aborted" in msg:
            return "connection_error"
        if "connection refused" in msg:
            return "connection_refused"
        return "client_transport_error"

    if 500 <= code < 600:
        return "server_5xx"

    if 400 <= code < 500:
        return "client_4xx"

    return "http_error"


def load_latency_files(run_dir, input_specs):
    frames = []

    if input_specs:
        specs = []
        for spec in input_specs:
            # role,instance,path
            role, instance, path = spec.split(",", 2)
            specs.append((role, instance, path))
    else:
        specs = DEFAULT_FILES

    seen_paths = set()

    for role, instance, rel_path in specs:
        path = Path(rel_path)
        if not path.is_absolute():
            path = Path(run_dir) / path

        if not path.exists():
            continue

        if str(path) in seen_paths:
            continue
        seen_paths.add(str(path))

        df = pd.read_csv(path)

        if "client_ts" not in df.columns:
            raise ValueError(f"{path} missing client_ts column")

        if "success" not in df.columns:
            df["success"] = 0

        if "status_code" not in df.columns:
            df["status_code"] = 0

        if "error_msg" not in df.columns:
            df["error_msg"] = ""

        if "latency_ms_client" not in df.columns:
            df["latency_ms_client"] = pd.NA

        if "server_latency_ms" not in df.columns:
            df["server_latency_ms"] = pd.NA

        df["service_role"] = role
        df["instance_name"] = instance
        df["source_file"] = str(path)
        df["ts"] = pd.to_datetime(df["client_ts"], errors="coerce")

        df["success_bool"] = df["success"].apply(parse_success)
        df["status_code_num"] = pd.to_numeric(df["status_code"], errors="coerce").fillna(0).astype(int)
        df["latency_ms_client_num"] = pd.to_numeric(df["latency_ms_client"], errors="coerce")
        df["server_latency_ms_num"] = pd.to_numeric(df["server_latency_ms"], errors="coerce")

        df["failure_type"] = [
            classify_failure(sc, em)
            for sc, em in zip(df["status_code_num"], df["error_msg"])
        ]

        df["request_failed"] = (
            (~df["success_bool"]) |
            (df["status_code_num"] < 200) |
            (df["status_code_num"] >= 300)
        )

        df["unreachable_failure"] = (
            df["request_failed"] &
            df["failure_type"].isin([
                "connect_timeout",
                "read_timeout",
                "remote_disconnected",
                "connection_error",
                "connection_refused",
                "client_transport_error",
            ])
        )

        frames.append(df)

    if not frames:
        raise FileNotFoundError(
            f"No latency csv found in {run_dir}. "
            f"Expected focus_inst1.csv, bg_inst2.csv, bg_inst3.csv "
            f"or raw_latency/*_raw.csv"
        )

    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["ts"]).sort_values(["ts", "instance_name"]).reset_index(drop=True)
    return out


def detect_outage_windows(df, window_sec, min_instances, min_failures, merge_gap_sec, buffer_sec):
    failed = df[df["unreachable_failure"]].copy()

    if failed.empty:
        return pd.DataFrame(columns=[
            "outage_id",
            "core_start",
            "core_end",
            "expanded_start",
            "expanded_end",
            "duration_sec",
            "expanded_duration_sec",
            "failed_instances",
            "failure_count",
            "failure_types",
        ])

    run_start = df["ts"].min().floor("s")
    run_end = df["ts"].max().ceil("s")
    timeline = pd.date_range(run_start, run_end, freq="1s")

    candidate_times = []

    for t in timeline:
        w_start = t - pd.Timedelta(seconds=window_sec - 1)
        w_end = t

        sub = failed[(failed["ts"] >= w_start) & (failed["ts"] <= w_end)]

        if sub.empty:
            continue

        failed_instances = sub["instance_name"].nunique()
        failure_count = len(sub)

        if failed_instances >= min_instances and failure_count >= min_failures:
            candidate_times.append(t)

    if not candidate_times:
        return pd.DataFrame(columns=[
            "outage_id",
            "core_start",
            "core_end",
            "expanded_start",
            "expanded_end",
            "duration_sec",
            "expanded_duration_sec",
            "failed_instances",
            "failure_count",
            "failure_types",
        ])

    # merge candidate seconds
    windows = []
    start = candidate_times[0]
    prev = candidate_times[0]

    for t in candidate_times[1:]:
        gap = (t - prev).total_seconds()
        if gap <= merge_gap_sec:
            prev = t
        else:
            windows.append((start, prev))
            start = t
            prev = t
    windows.append((start, prev))

    records = []

    for i, (start, end) in enumerate(windows, start=1):
        # include the lookback window used by rolling detection
        core_start = start - pd.Timedelta(seconds=window_sec - 1)
        core_end = end

        expanded_start = core_start - pd.Timedelta(seconds=buffer_sec)
        expanded_end = core_end + pd.Timedelta(seconds=buffer_sec)

        sub = failed[(failed["ts"] >= core_start) & (failed["ts"] <= core_end)]

        records.append({
            "outage_id": f"outage_{i:03d}",
            "core_start": core_start,
            "core_end": core_end,
            "expanded_start": expanded_start,
            "expanded_end": expanded_end,
            "duration_sec": (core_end - core_start).total_seconds(),
            "expanded_duration_sec": (expanded_end - expanded_start).total_seconds(),
            "failed_instances": sub["instance_name"].nunique(),
            "failure_count": len(sub),
            "failure_types": ",".join(sorted(sub["failure_type"].dropna().unique())),
        })

    return pd.DataFrame(records)


def label_rows(df, windows, latency_degraded_ms):
    df = df.copy()

    df["outage_id"] = ""
    df["service_state"] = "reachable"
    df["availability_label"] = "reachable"
    df["sample_label"] = "clean_success"

    for _, w in windows.iterrows():
        core_start = pd.to_datetime(w["core_start"])
        core_end = pd.to_datetime(w["core_end"])
        exp_start = pd.to_datetime(w["expanded_start"])
        exp_end = pd.to_datetime(w["expanded_end"])
        outage_id = w["outage_id"]

        in_exp = (df["ts"] >= exp_start) & (df["ts"] <= exp_end)
        in_core = (df["ts"] >= core_start) & (df["ts"] <= core_end)

        df.loc[in_exp, "outage_id"] = outage_id
        df.loc[in_exp, "service_state"] = "outage_buffer"
        df.loc[in_exp, "availability_label"] = "outage_buffer"

        df.loc[in_core, "service_state"] = "service_unreachable"
        df.loc[in_core, "availability_label"] = "service_unreachable"

    latency_degraded = (
        df["success_bool"] &
        df["latency_ms_client_num"].notna() &
        (df["latency_ms_client_num"] > latency_degraded_ms)
    )

    df.loc[df["request_failed"] & (df["service_state"] == "service_unreachable"), "sample_label"] = "failed_service_unreachable"
    df.loc[df["success_bool"] & (df["service_state"] == "service_unreachable"), "sample_label"] = "success_inside_unreachable_window"
    df.loc[df["service_state"] == "outage_buffer", "sample_label"] = "outage_buffer"
    df.loc[df["request_failed"] & (df["service_state"] == "reachable"), "sample_label"] = "isolated_request_failure"
    df.loc[latency_degraded & (df["service_state"] == "reachable"), "sample_label"] = "latency_degraded"

    df["use_for_clean_baseline"] = (
        df["success_bool"] &
        (df["service_state"] == "reachable") &
        df["latency_ms_client_num"].notna() &
        df["server_latency_ms_num"].notna() &
        (df["latency_ms_client_num"] <= latency_degraded_ms)
    ).astype(int)

    df["use_for_latency_regression"] = df["use_for_clean_baseline"]
    df["use_for_qos_anomaly"] = 1

    return df


def build_clean_segments(df, windows, min_clean_segment_sec):
    run_start = df["ts"].min()
    run_end = df["ts"].max()

    expanded = []

    for _, w in windows.iterrows():
        expanded.append((
            pd.to_datetime(w["expanded_start"]),
            pd.to_datetime(w["expanded_end"]),
        ))

    expanded = sorted(expanded, key=lambda x: x[0])

    # merge overlapping expanded windows
    merged = []
    for s, e in expanded:
        if not merged or s > merged[-1][1]:
            merged.append([s, e])
        else:
            merged[-1][1] = max(merged[-1][1], e)

    segments = []
    cursor = run_start
    seg_id = 1

    for s, e in merged:
        if s > cursor:
            duration = (s - cursor).total_seconds()
            if duration >= min_clean_segment_sec:
                segments.append({
                    "segment_id": f"clean_segment_{seg_id:03d}",
                    "segment_start": cursor,
                    "segment_end": s,
                    "duration_sec": duration,
                    "reason": "outside_outage_window",
                })
                seg_id += 1
        cursor = max(cursor, e)

    if cursor < run_end:
        duration = (run_end - cursor).total_seconds()
        if duration >= min_clean_segment_sec:
            segments.append({
                "segment_id": f"clean_segment_{seg_id:03d}",
                "segment_start": cursor,
                "segment_end": run_end,
                "duration_sec": duration,
                "reason": "outside_outage_window",
            })

    return pd.DataFrame(segments)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--input", action="append", help="role,instance,path")
    parser.add_argument("--window-sec", type=int, default=5)
    parser.add_argument("--min-instances", type=int, default=2)
    parser.add_argument("--min-failures", type=int, default=2)
    parser.add_argument("--merge-gap-sec", type=int, default=5)
    parser.add_argument("--buffer-sec", type=int, default=10)
    parser.add_argument("--latency-degraded-ms", type=float, default=1000.0)
    parser.add_argument("--min-clean-segment-sec", type=float, default=60.0)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    out_dir = run_dir / "outage_labeling"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_latency_files(run_dir, args.input)

    windows = detect_outage_windows(
        df=df,
        window_sec=args.window_sec,
        min_instances=args.min_instances,
        min_failures=args.min_failures,
        merge_gap_sec=args.merge_gap_sec,
        buffer_sec=args.buffer_sec,
    )

    labeled = label_rows(df, windows, args.latency_degraded_ms)
    clean_segments = build_clean_segments(labeled, windows, args.min_clean_segment_sec)

    labeled_out = out_dir / "latency_3inst_outage_labeled.csv"
    windows_out = out_dir / "service_outage_windows.csv"
    segments_out = out_dir / "clean_segments.csv"
    clean_out = out_dir / "latency_3inst_clean_success.csv"
    summary_out = out_dir / "outage_label_summary.csv"

    labeled.to_csv(labeled_out, index=False)
    windows.to_csv(windows_out, index=False)
    clean_segments.to_csv(segments_out, index=False)
    labeled[labeled["use_for_clean_baseline"] == 1].to_csv(clean_out, index=False)

    summary = (
        labeled.groupby(["instance_name", "availability_label", "sample_label"])
        .size()
        .reset_index(name="count")
        .sort_values(["instance_name", "availability_label", "sample_label"])
    )
    summary.to_csv(summary_out, index=False)

    print("wrote:", labeled_out)
    print("wrote:", windows_out)
    print("wrote:", segments_out)
    print("wrote:", clean_out)
    print("wrote:", summary_out)
    print()

    print("=== service_outage_windows ===")
    if len(windows) == 0:
        print("No synchronized service outage detected.")
    else:
        print(windows.to_string(index=False))

    print()
    print("=== clean_segments ===")
    if len(clean_segments) == 0:
        print("No clean segment longer than threshold.")
    else:
        print(clean_segments.to_string(index=False))

    print()
    print("=== summary ===")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
