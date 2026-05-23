import sys
from pathlib import Path
import pandas as pd

run_dir = Path(sys.argv[1])
gpu_path = run_dir / "nvidia_smi_gpu_1s.csv"

df = pd.read_csv(gpu_path)

def to_float(s):
    return (
        s.astype(str)
        .str.replace(" %", "", regex=False)
        .str.replace(" W", "", regex=False)
        .str.replace(" MiB", "", regex=False)
        .str.replace(" MHz", "", regex=False)
        .str.strip()
        .astype(float)
    )

time_col = df.columns[0]
df["timestamp_dt"] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
df["t_rel_sec"] = (df["timestamp_dt"] - df["timestamp_dt"].iloc[0]).dt.total_seconds()

gpu_col = [c for c in df.columns if "utilization.gpu" in c][0]
mem_col = [c for c in df.columns if "utilization.memory" in c][0]
power_col = [c for c in df.columns if "power.draw" in c][0]
temp_col = [c for c in df.columns if "temperature.gpu" in c][0]

df["gpu_util"] = to_float(df[gpu_col])
df["mem_util"] = to_float(df[mem_col])
df["power_w"] = to_float(df[power_col])
df["temp_c"] = to_float(df[temp_col])

# rolling 5-second steady condition
df["gpu_roll_mean"] = df["gpu_util"].rolling(window=5, min_periods=5).mean()
df["power_roll_mean"] = df["power_w"].rolling(window=5, min_periods=5).mean()

# 條件可依實驗需求調整
df["stable"] = (
    (df["t_rel_sec"] >= 20) &
    (df["gpu_roll_mean"] >= 80) &
    (df["power_roll_mean"] >= 180)
)

# 找最長連續 stable segment
segments = []
start = None
prev_idx = None

for idx, row in df.iterrows():
    if row["stable"]:
        if start is None:
            start = idx
        prev_idx = idx
    else:
        if start is not None:
            segments.append((start, prev_idx))
            start = None
            prev_idx = None

if start is not None:
    segments.append((start, prev_idx))

print(f"RUN_DIR={run_dir}")
print(f"Total samples={len(df)}")
print(f"Stable samples={int(df['stable'].sum())}")

if not segments:
    print("[FAIL] No stable window found.")
    print("Reason: GPU utilization / power is still too bursty.")
    sys.exit(1)

segments = sorted(segments, key=lambda x: x[1] - x[0] + 1, reverse=True)
s, e = segments[0]
steady = df.loc[s:e].copy()

duration = steady["t_rel_sec"].iloc[-1] - steady["t_rel_sec"].iloc[0]
out = run_dir / "gpu_stable_window_auto.csv"
steady.to_csv(out, index=False)

print(f"Selected stable window: {steady['t_rel_sec'].iloc[0]:.1f}s to {steady['t_rel_sec'].iloc[-1]:.1f}s")
print(f"Duration: {duration:.1f}s")
print(f"Saved: {out}")

if duration < 30:
    print("[WARN] Stable window shorter than 30s. This run is not ideal for formal analysis.")

for name in ["gpu_util", "mem_util", "power_w", "temp_c"]:
    print(f"\\n== stable {name} ==")
    print(steady[name].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))
