import sys
import pandas as pd
from pathlib import Path

if len(sys.argv) != 2:
    print("Usage: python3 common/analyze_task3_stable_latency.py <RUN_DIR>")
    sys.exit(1)

run = Path(sys.argv[1])

nvidia_path = run / "nvidia_smi_gpu_1s.csv"
windows_path = run / "stable_windows.csv"

if not nvidia_path.exists():
    raise FileNotFoundError(nvidia_path)
if not windows_path.exists():
    raise FileNotFoundError(windows_path)

gpu_df = pd.read_csv(nvidia_path)
windows = pd.read_csv(windows_path)

# 找 nvidia-smi timestamp 欄位
timestamp_cols = [c for c in gpu_df.columns if "timestamp" in c.lower()]

if timestamp_cols:
    ts_col = timestamp_cols[0]

    # nvidia-smi timestamp 通常是 node local time，例如台灣時間 +08:00。
    # 不能直接 utc=True，否則會把 15:20 誤判成 15:20Z，
    # 和 request log 的 07:20Z 差 8 小時。
    raw_ts = pd.to_datetime(gpu_df[ts_col], errors="coerce")

    if getattr(raw_ts.dt, "tz", None) is None:
        gpu_df["_gpu_ts"] = raw_ts.dt.tz_localize("Asia/Taipei").dt.tz_convert("UTC")
    else:
        gpu_df["_gpu_ts"] = raw_ts.dt.tz_convert("UTC")

    gpu_df = gpu_df.dropna(subset=["_gpu_ts"]).reset_index(drop=True)
    t0 = gpu_df["_gpu_ts"].iloc[0]
else:
    # fallback：如果 nvidia_smi 沒有 timestamp，就用 request 最早時間當作 t0
    all_req = []
    for name in ["measurement_raw.csv", "background_raw.csv"]:
        df_tmp = pd.read_csv(run / name)
        df_tmp["client_ts_start"] = pd.to_datetime(df_tmp["client_ts_start"], utc=True, errors="coerce")
        all_req.append(df_tmp["client_ts_start"].min())
    t0 = min(all_req)
    print("[WARN] No timestamp column in nvidia_smi_gpu_1s.csv. Use earliest request time as t0.")

print("t0:", t0)

def assign_window(mid_rel_s):
    for _, w in windows.iterrows():
        if float(w["start_s"]) <= mid_rel_s <= float(w["end_s"]):
            return w["window_id"]
    return None

def process_request_csv(name, expected_role):
    path = run / name
    if not path.exists():
        print("\n==============================")
        print(name)
        print("==============================")
        print("missing:", path)
        print("skip.")
        return pd.DataFrame()

    df = pd.read_csv(path)

    df["client_ts_start"] = pd.to_datetime(df["client_ts_start"], utc=True, errors="coerce")
    df["client_ts_end"] = pd.to_datetime(df["client_ts_end"], utc=True, errors="coerce")

    df["client_mid_ts"] = df["client_ts_start"] + (df["client_ts_end"] - df["client_ts_start"]) / 2
    df["t_rel_s"] = (df["client_ts_start"] - t0).dt.total_seconds()
    df["mid_t_rel_s"] = (df["client_mid_ts"] - t0).dt.total_seconds()

    for col in ["e2e_latency_ms", "server_latency_ms", "server_total_latency_ms"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "e2e_latency_ms" in df.columns and "server_total_latency_ms" in df.columns:
        df["overhead_ms"] = df["e2e_latency_ms"] - df["server_total_latency_ms"]
    else:
        df["overhead_ms"] = pd.NA

    df["window_id"] = df["mid_t_rel_s"].apply(assign_window)

    # raw with window labels
    labeled_path = run / name.replace("_raw.csv", "_with_windows.csv")
    df.to_csv(labeled_path, index=False)

    clean = df[
        (df["success"] == True)
        & (df["status_code"] == 200)
        & (df["error_type"] == "normal_success")
        & (df["server_service_role"] == expected_role)
        & (df["server_latency_ms"].notna())
        & (df["server_total_latency_ms"].notna())
        & (df["e2e_latency_ms"].notna())
        & (df["overhead_ms"].notna())
        & (df["window_id"].notna())
    ].copy()

    clean_path = run / name.replace("_raw.csv", "_stable_clean.csv")
    clean.to_csv(clean_path, index=False)

    print("\n==============================")
    print(name)
    print("==============================")
    print("raw rows:", len(df))
    print("stable clean rows:", len(clean))
    print("saved:", clean_path)

    print("\nrole distribution, raw:")
    print(df["server_service_role"].value_counts(dropna=False))

    print("\nrole distribution, stable clean:")
    print(clean["server_service_role"].value_counts(dropna=False))

    print("\nwindow distribution:")
    print(clean["window_id"].value_counts(dropna=False))

    if len(clean) > 0:
        print("\ne2e latency by window:")
        print(clean.groupby("window_id")["e2e_latency_ms"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

        print("\nserver latency by window:")
        print(clean.groupby("window_id")["server_latency_ms"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

        print("\nserver total latency by window:")
        print(clean.groupby("window_id")["server_total_latency_ms"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

        print("\noverhead by window:")
        print(clean.groupby("window_id")["overhead_ms"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

    return clean

measurement_clean = process_request_csv("measurement_raw.csv", "focus")
background_clean = process_request_csv("background_raw.csv", "background")

print("\n[Done]")
print("Generated files:")
print(run / "measurement_with_windows.csv")
print(run / "background_with_windows.csv")
print(run / "measurement_stable_clean.csv")
print(run / "background_stable_clean.csv")
