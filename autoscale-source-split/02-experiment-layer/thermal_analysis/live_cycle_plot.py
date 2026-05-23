#!/usr/bin/env python3
import argparse
import os
import glob
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def pick_col(df, candidates):
    cols = {str(c).lower(): c for c in df.columns}
    for c in candidates:
        if c in df.columns:
            return c
        if c.lower() in cols:
            return cols[c.lower()]
    return None


def to_num(s):
    return pd.to_numeric(s, errors="coerce")


def load_thermal_csv(path: Path):
    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]

    x_col = pick_col(df, ["elapsed_s", "elapsed_sec", "elapsed_seconds"])
    ts_col = pick_col(df, ["timestamp", "ts", "time"])

    if x_col:
        df["x"] = to_num(df[x_col])
    elif ts_col:
        t = pd.to_datetime(df[ts_col], errors="coerce")
        df["x"] = (t - t.dropna().iloc[0]).dt.total_seconds()
    else:
        df["x"] = range(len(df))

    df["elapsed_s"] = to_num(df["x"])
    return df


def expand_latency_files(latency_glob: str, run_dir: Path, latency_client: str):
    patterns = []

    if latency_glob:
        patterns.append(latency_glob)

    # fallback：從 RUN_DIR/raw_latency 自動找
    patterns += [
        str(run_dir / "raw_latency" / f"*{latency_client}*raw*.csv"),
        str(run_dir / "raw_latency" / f"*{latency_client}*.csv"),
        str(run_dir / "raw_latency" / "*raw*.csv"),
        str(run_dir / "raw_latency" / "*.csv"),
    ]

    files = []
    for pat in patterns:
        files.extend(glob.glob(os.path.expanduser(pat)))

    # 去重並排序
    out = []
    seen = set()
    for f in sorted(files):
        p = Path(f)
        if p not in seen and p.exists():
            out.append(p)
            seen.add(p)

    # 優先取檔名含 focus 的
    focus_files = [f for f in out if latency_client.lower() in f.name.lower()]
    return focus_files if focus_files else out


def load_focus_latency(run_dir: Path, latency_glob: str, latency_client: str, thermal_t0=None):
    files = expand_latency_files(latency_glob, run_dir, latency_client)

    if not files:
        print("[WARN] no latency csv found")
        return pd.DataFrame()

    dfs = []

    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception as e:
            print(f"[WARN] failed to read latency file: {f}, err={e}")
            continue

        if len(df) == 0:
            continue

        df.columns = [str(c).strip() for c in df.columns]
        df["source_file"] = f.name

        # 若同一檔內有 client / service 欄位，過濾 focus
        for c in ["client", "client_name", "service", "deployment", "target", "name", "role"]:
            if c in df.columns:
                m = df[c].astype(str).str.lower().str.contains(latency_client.lower(), na=False)
                if m.any():
                    df = df[m].copy()
                break

        dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True)

    # server latency 欄位優先
    latency_col = pick_col(df, [
        "server_latency_ms",
        "latency_ms_server",
        "server_ms",
        "inference_ms",
        "model_latency_ms",
        "latency_server_ms",
        "latency_ms",
    ])

    if not latency_col:
        print("[WARN] no server latency column found")
        print("[WARN] latency columns =", list(df.columns))
        return pd.DataFrame()

    df["server_latency_ms"] = to_num(df[latency_col])

    # 優先用 timestamp 對齊 thermal 起點，這樣可以保留 thermal command 啟動前的 baseline 負時間
    ts_col = pick_col(df, ["client_ts", "timestamp", "ts", "time", "datetime"])
    elapsed_col = pick_col(df, ["elapsed_s", "elapsed_sec", "elapsed_seconds", "time_s"])

    if ts_col and thermal_t0 is not None:
        t = pd.to_datetime(df[ts_col], errors="coerce")
        df["x"] = (t - thermal_t0).dt.total_seconds()
    elif elapsed_col:
        df["x"] = to_num(df[elapsed_col])
    else:
        df["x"] = range(len(df))

    # 只畫有效 server latency
    df = df.dropna(subset=["x", "server_latency_ms"]).copy()
    df["elapsed_s"] = to_num(df["x"])

    # 若有 success 欄位，優先只畫成功請求
    for c in ["success_bool", "success", "ok"]:
        if c in df.columns:
            s = df[c]
            if s.dtype == bool:
                df = df[s].copy()
            else:
                df = df[s.astype(str).str.lower().isin(["true", "1", "yes", "ok", "success"])].copy()
            break

    print(f"[INFO] latency files used: {[str(f) for f in files]}")
    print(f"[INFO] focus latency rows: {len(df)}")

    return df.sort_values("x")


def get_target(args, thermal_df):
    for v in [
        args.target,
        os.environ.get("PLOT_TARGET_C"),
        os.environ.get("TARGET_TEMP_C"),
        os.environ.get("TARGET_TEMP"),
        os.environ.get("FAULT_TEMP_C"),
        os.environ.get("FAULT_TEMP"),
        os.environ.get("HIGH_TEMP_C"),
        os.environ.get("HIGH_TEMP"),
    ]:
        if v not in [None, ""]:
            try:
                return float(v)
            except Exception:
                pass

    for c in ["target_temp_c", "target_c"]:
        if c in thermal_df.columns:
            vals = pd.to_numeric(thermal_df[c], errors="coerce").dropna()
            if len(vals) > 0:
                return float(vals.iloc[-1])

    return 90.0


def add_phase_lines(ax, thermal_df):
    if "phase" not in thermal_df.columns or "x" not in thermal_df.columns:
        return

    tmp = thermal_df[["x", "phase"]].dropna().copy()
    if len(tmp) == 0:
        return

    last = None
    for _, row in tmp.iterrows():
        ph = row["phase"]
        if ph != last:
            ax.axvline(row["x"], linestyle="--", linewidth=0.8, alpha=0.35)
            last = ph


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", "--input", "--thermal-csv", dest="thermal_csv")
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", type=float, default=None)
    ap.add_argument("--latency-glob", default=os.environ.get("LATENCY_GLOB", ""))
    ap.add_argument("--latency-client", default=os.environ.get("LATENCY_CLIENT", "focus"))
    ap.add_argument("--title", default="")
    args, _ = ap.parse_known_args()

    if not args.thermal_csv:
        raise SystemExit("missing --csv / --thermal-csv")

    thermal_csv = Path(args.thermal_csv).expanduser()
    out_path = Path(args.out).expanduser()
    run_dir = out_path.parent

    thermal_df = load_thermal_csv(thermal_csv)

    ts_col = pick_col(thermal_df, ["timestamp", "ts", "time"])
    thermal_t0 = None
    if ts_col:
        tt = pd.to_datetime(thermal_df[ts_col], errors="coerce").dropna()
        if len(tt) > 0:
            thermal_t0 = tt.iloc[0]

    target = get_target(args, thermal_df)
    latency_df = load_focus_latency(
        run_dir=run_dir,
        latency_glob=args.latency_glob,
        latency_client=args.latency_client,
        thermal_t0=thermal_t0,
    )

    temp_col = pick_col(thermal_df, ["gpu_temp_c", "temperature_gpu_c", "temp_c"])
    fan_col = pick_col(thermal_df, ["gpu_fan_pct", "fan_pct", "fan_speed_pct"])
    sm_col = pick_col(thermal_df, ["gpu_clock_mhz", "clocks_sm_mhz", "sm_clock_mhz", "clocksm_mhz"])

    fig, axes = plt.subplots(4, 1, figsize=(14, 9), sharex=False)

    fig_title = args.title or "YOLO26 Thermal / Fan / SM Clock / Focus Server Latency"
    fig.suptitle(fig_title)

    # 1. GPU temperature
    ax = axes[0]
    if temp_col:
        ax.plot(thermal_df["x"], to_num(thermal_df[temp_col]), label="GPU Temp")
    ax.axhline(target, linestyle="--", label="Target")
    ax.set_ylabel("Temp (C)")
    ax.set_title("GPU Temperature Control")
    add_phase_lines(ax, thermal_df)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")

    # 2. Fan
    ax = axes[1]
    if fan_col:
        ax.plot(thermal_df["x"], to_num(thermal_df[fan_col]), label="Fan %")
    ax.set_ylabel("Fan (%)")
    ax.set_title("Fan Control")
    add_phase_lines(ax, thermal_df)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")

    # 3. SM Clock
    ax = axes[2]
    if sm_col:
        ax.plot(thermal_df["x"], to_num(thermal_df[sm_col]), label="SM Clock")
    ax.set_ylabel("SM Clock (MHz)")
    ax.set_title("GPU SM Clock")
    add_phase_lines(ax, thermal_df)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")

    # 4. YOLO Focus Server Latency
    ax = axes[3]
    if latency_df is not None and len(latency_df) > 0:
        lat = latency_df.copy()

        # 只保留 focus
        if "role" in lat.columns:
            lat = lat[lat["role"].astype(str).str.lower().eq("focus")].copy()
        elif "service_role" in lat.columns:
            lat = lat[lat["service_role"].astype(str).str.lower().eq("focus")].copy()
        elif "YOLO26_SERVICE_ROLE" in lat.columns:
            lat = lat[lat["YOLO26_SERVICE_ROLE"].astype(str).str.lower().eq("focus")].copy()

        # 轉數值
        lat["elapsed_s"] = pd.to_numeric(lat["elapsed_s"], errors="coerce")

        if "server_latency_ms" in lat.columns:
            latency_col = "server_latency_ms"
        elif "server_latency_ms_num" in lat.columns:
            latency_col = "server_latency_ms_num"
        else:
            latency_col = None

        if latency_col is not None:
            lat[latency_col] = pd.to_numeric(lat[latency_col], errors="coerce")
            lat = lat.dropna(subset=["elapsed_s", latency_col]).sort_values("elapsed_s")

            # 只畫成功請求，避免 unreachable / failed 拉亂圖
            if "success" in lat.columns:
                lat = lat[lat["success"].astype(str).isin(["1", "True", "true"])].copy()
            elif "success_bool" in lat.columns:
                lat = lat[lat["success_bool"] == True].copy()

            # 讓 latency 圖的時間範圍跟 thermal 圖一致
            if "elapsed_s" in thermal_df.columns:
                t_min = pd.to_numeric(thermal_df["elapsed_s"], errors="coerce").min()
                t_max = pd.to_numeric(thermal_df["elapsed_s"], errors="coerce").max()
                lat = lat[(lat["elapsed_s"] >= t_min) & (lat["elapsed_s"] <= t_max)].copy()

        if latency_col is not None and len(lat) > 0:
            # 折線圖，不要點狀圖
            ax.plot(
                lat["elapsed_s"],
                lat[latency_col],
                linestyle="-",
                linewidth=0.8,
                marker=None,
                label="focus Server Latency",
            )
    ax.set_title("YOLO Focus Server Latency")
    ax.set_ylabel("Server Latency (ms)")
    ax.set_xlabel("Elapsed Seconds")
    ax.legend()
    ax.grid(True, alpha=0.3)
    add_phase_lines(ax, thermal_df)

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150)
    plt.close()

    print(f"[OK] wrote plot: {out_path}")


if __name__ == "__main__":
    main()
