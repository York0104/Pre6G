#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Optional, List, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# -----------------------------
# Utility
# -----------------------------
def find_first_existing(run_dir: Path, names: List[str]) -> Optional[Path]:
    for name in names:
        p = run_dir / name
        if p.exists():
            return p
    return None


def find_latency_csv(run_dir: Path) -> Optional[Path]:
    preferred = [
        "latency.csv",
        "latency_trimmed.csv",
        "latency_pairs.csv",
        "latency_pairs_trimmed.csv",
        "merged_latency.csv",
        "service_latency.csv",
    ]

    p = find_first_existing(run_dir, preferred)
    if p:
        return p

    candidates = sorted(
        [
            x for x in run_dir.glob("**/*.csv")
            if "latency" in x.name.lower()
            and "summary" not in x.name.lower()
        ]
    )
    return candidates[0] if candidates else None


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = list(df.columns)
    for c in candidates:
        if c in cols:
            return c
    return None


def pick_col_contains(df: pd.DataFrame, keywords: List[str], exclude: Optional[List[str]] = None) -> Optional[str]:
    exclude = exclude or []
    cols = list(df.columns)
    for c in cols:
        lc = c.lower()
        if all(k.lower() in lc for k in keywords) and not any(e.lower() in lc for e in exclude):
            return c
    return None


def ensure_elapsed_seconds(df: pd.DataFrame) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    找出時間軸欄位並統一成 __elapsed_s__
    """
    df = df.copy()

    direct_candidates = [
        "elapsed_s",
        "elapsed_sec",
        "elapsed_secs",
        "elapsed_seconds",
        "seconds",
        "t_sec",
        "time_s",
    ]
    c = pick_col(df, direct_candidates)
    if c:
        df["__elapsed_s__"] = pd.to_numeric(df[c], errors="coerce")
        return df, "__elapsed_s__"

    # 若有 timestamp 類欄位，轉成相對秒數
    ts_candidates = [
        "timestamp",
        "ts",
        "time",
        "datetime",
        "client_ts",
        "server_ts",
    ]
    for tc in ts_candidates:
        if tc in df.columns:
            t = pd.to_datetime(df[tc], errors="coerce")
            if t.notna().sum() > 1:
                df["__elapsed_s__"] = (t - t.dropna().iloc[0]).dt.total_seconds()
                return df, "__elapsed_s__"

    return df, None


def detect_phase_column(df: pd.DataFrame) -> Optional[str]:
    return pick_col(df, ["phase", "stage", "segment"])


def phase_boundaries(df: pd.DataFrame) -> List[Tuple[float, str]]:
    """
    從 phase 欄位抓出切換點，用來畫垂直虛線與標籤
    """
    df = df.copy()
    if "__elapsed_s__" not in df.columns:
        return []

    phase_col = detect_phase_column(df)
    if not phase_col:
        return []

    tmp = df[[ "__elapsed_s__", phase_col ]].copy()
    tmp = tmp.dropna(subset=["__elapsed_s__", phase_col])
    if tmp.empty:
        return []

    tmp[phase_col] = tmp[phase_col].astype(str)
    out = []
    prev = None
    for _, row in tmp.iterrows():
        ph = row[phase_col]
        t = float(row["__elapsed_s__"])
        if ph != prev:
            out.append((t, ph))
            prev = ph
    return out


def add_phase_guides(ax, boundaries: List[Tuple[float, str]], ymax_pad_ratio: float = 0.98):
    if not boundaries:
        return

    ymin, ymax = ax.get_ylim()
    y_text = ymin + (ymax - ymin) * ymax_pad_ratio

    for t, ph in boundaries:
        ax.axvline(t, linestyle=":", linewidth=1.2, alpha=0.7)
        ax.text(
            t + 2,
            y_text,
            ph,
            fontsize=8,
            va="top",
            ha="left",
            alpha=0.85
        )


def safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


# -----------------------------
# Data extraction
# -----------------------------
def extract_thermal(run_dir: Path) -> pd.DataFrame:
    thermal_path = find_first_existing(
        run_dir,
        [
            "thermal.csv",
            "worker_logs/thermal.csv",
            "worker_logs_live/thermal.csv",
        ],
    )

    if not thermal_path:
        candidates = sorted(run_dir.glob("**/*thermal*.csv"))
        thermal_path = candidates[0] if candidates else None

    if not thermal_path:
        raise FileNotFoundError(
            f"找不到 thermal 類 csv，run_dir={run_dir}"
        )

    print(f"[plot] thermal source: {thermal_path}")

    df = load_csv(thermal_path)
    df, _ = ensure_elapsed_seconds(df)

    temp_col = (
        pick_col(df, ["temp_c", "gpu_temp_c", "temperature_c"])
        or pick_col_contains(df, ["temp"], exclude=["memory"])
    )
    fan_col = (
        pick_col(df, ["fan_percent", "fan_pct", "fan"])
        or pick_col_contains(df, ["fan"])
    )

    target_col = pick_col(df, ["target_c", "target_temp_c", "target"])
    band_plus_col = pick_col(df, ["band_plus_c", "band_high_c", "upper_band_c"])
    band_minus_col = pick_col(df, ["band_minus_c", "band_low_c", "lower_band_c"])

    out = pd.DataFrame({
        "elapsed_s": df["__elapsed_s__"]
    })
    out["temp_c"] = safe_numeric(df[temp_col]) if temp_col else np.nan
    out["fan_pct"] = safe_numeric(df[fan_col]) if fan_col else np.nan
    out["target_c"] = safe_numeric(df[target_col]) if target_col else np.nan
    out["band_plus_c"] = safe_numeric(df[band_plus_col]) if band_plus_col else np.nan
    out["band_minus_c"] = safe_numeric(df[band_minus_col]) if band_minus_col else np.nan

    phase_col = detect_phase_column(df)
    if phase_col:
        out["phase"] = df[phase_col].astype(str)
    else:
        out["phase"] = None

    return out


def extract_smclock(run_dir: Path) -> pd.DataFrame:
    aligned_path = find_first_existing(
        run_dir,
        [
            "aligned_metrics.csv",
            "worker_logs/aligned_metrics.csv",
        ],
    )

    if not aligned_path:
        candidates = sorted(run_dir.glob("**/aligned_metrics.csv"))
        aligned_path = candidates[0] if candidates else None

    if not aligned_path:
        raise FileNotFoundError(f"找不到 aligned_metrics.csv，run_dir={run_dir}")

    print(f"[plot] aligned source: {aligned_path}")

    df = load_csv(aligned_path)
    df, _ = ensure_elapsed_seconds(df)

    sm_clock_col = (
        pick_col(df, [
            "metrics__target_node_semantic__gpu_bound_features__gpu_compute__sm_clock_mhz_avg",
            "metrics__target_node_semantic__gpu_bound_features__compute_proxy__sm_clock_mhz_avg",
        ])
        or pick_col_contains(df, ["sm_clock"])
    )

    if not sm_clock_col:
        raise KeyError("找不到 SM clock 欄位，請檢查 aligned_metrics.csv")

    out = pd.DataFrame({
        "elapsed_s": df["__elapsed_s__"],
        "sm_clock_mhz": safe_numeric(df[sm_clock_col]),
    })

    # 若 aligned_metrics.csv 本身也有 phase，可直接用
    phase_col = detect_phase_column(df)
    if phase_col:
        out["phase"] = df[phase_col].astype(str)
    return out


def compute_smclock_drop(sm_df: pd.DataFrame, thermal_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    sm_df = sm_df.copy()
    phase_source = None

    # 優先使用 sm_df 的 phase；若沒有，再從 thermal_df 依時間近似帶入
    if "phase" in sm_df.columns and sm_df["phase"].notna().any():
        phase_source = sm_df["phase"]
    elif thermal_df is not None and "phase" in thermal_df.columns:
        # 以 elapsed_s 最近鄰對應 phase
        t2 = thermal_df[["elapsed_s", "phase"]].dropna().sort_values("elapsed_s").copy()
        s2 = sm_df[["elapsed_s"]].dropna().sort_values("elapsed_s").copy()
        if not t2.empty and not s2.empty:
            merged = pd.merge_asof(
                s2, t2, on="elapsed_s", direction="nearest"
            )
            sm_df = sm_df.merge(merged, on="elapsed_s", how="left", suffixes=("", "_thermal"))
            if "phase_y" in sm_df.columns:
                sm_df["phase"] = sm_df["phase_y"]
            elif "phase_thermal" in sm_df.columns:
                sm_df["phase"] = sm_df["phase_thermal"]
            phase_source = sm_df.get("phase")

    baseline = None
    if phase_source is not None:
        mask = pd.Series(phase_source).astype(str).str.lower().eq("normal_hold")
        vals = sm_df.loc[mask, "sm_clock_mhz"].dropna()
        if len(vals) >= 5:
            baseline = float(vals.median())

    # 如果沒有 normal_hold，就用最高 10% 的中位數作 baseline
    if baseline is None or not np.isfinite(baseline) or baseline <= 0:
        vals = sm_df["sm_clock_mhz"].dropna().sort_values()
        if len(vals) == 0:
            baseline = 1.0
        else:
            n = max(1, math.ceil(len(vals) * 0.1))
            baseline = float(vals.tail(n).median())

    sm_df["sm_clock_drop_pct"] = (baseline - sm_df["sm_clock_mhz"]) / baseline * 100.0
    sm_df["sm_clock_drop_pct"] = sm_df["sm_clock_drop_pct"].clip(lower=0)

    return sm_df


def extract_latency(run_dir: Path) -> Optional[pd.DataFrame]:
    latency_path = find_latency_csv(run_dir)
    if not latency_path:
        return None

    df = load_csv(latency_path)
    df, time_col = ensure_elapsed_seconds(df)
    if time_col is None:
        return None

    # 常見 server/client latency 欄位名稱
    server_col = (
        pick_col(df, [
            "server_ms",
            "server_latency_ms",
            "server_rtt_ms",
            "latency_ms_server",
        ])
        or pick_col_contains(df, ["server", "latency"], exclude=["time", "ts", "phase", "count"])
        or pick_col_contains(df, ["latency", "server"], exclude=["time", "ts", "phase", "count"])
    )
    client_col = (
        pick_col(df, [
            "client_ms",
            "client_latency_ms",
            "client_rtt_ms",
            "latency_ms_client",
        ])
        or pick_col_contains(df, ["client", "latency"], exclude=["time", "ts", "phase", "count"])
        or pick_col_contains(df, ["latency", "client"], exclude=["time", "ts", "phase", "count"])
    )

    # 若只有單一 latency 欄位
    if server_col is None and client_col is None:
        one_col = (
            pick_col(df, ["latency_ms", "rtt_ms"])
            or pick_col_contains(df, ["latency"], exclude=["phase", "p95", "mean", "count"])
        )
        if one_col:
            client_col = one_col

    print(f"[plot] latency source: {latency_path}")
    print(f"[plot] server_col={server_col}, client_col={client_col}")

    out = pd.DataFrame({
        "elapsed_s": df["__elapsed_s__"]
    })

    if server_col:
        out["server_ms"] = safe_numeric(df[server_col])
    if client_col:
        out["client_ms"] = safe_numeric(df[client_col])

    if len(out.columns) <= 1:
        return None

    phase_col = detect_phase_column(df)
    if phase_col:
        out["phase"] = df[phase_col].astype(str)

    return out


# -----------------------------
# Plot
# -----------------------------
def plot_all(
    thermal_df: pd.DataFrame,
    sm_df: pd.DataFrame,
    latency_df: Optional[pd.DataFrame],
    output_path: Path,
    title: Optional[str] = None,
):
    fig, axes = plt.subplots(
        4, 1, figsize=(14, 10), sharex=True, constrained_layout=True
    )

    boundaries = phase_boundaries(thermal_df)

    # 1) Temp
    ax = axes[0]
    ax.plot(thermal_df["elapsed_s"], thermal_df["temp_c"], label="GPU Temp")
    if thermal_df["target_c"].notna().any():
        ax.plot(thermal_df["elapsed_s"], thermal_df["target_c"], linestyle="--", label="Target")
    if thermal_df["band_plus_c"].notna().any():
        ax.plot(thermal_df["elapsed_s"], thermal_df["band_plus_c"], linestyle="--", label="Band +")
    if thermal_df["band_minus_c"].notna().any():
        ax.plot(thermal_df["elapsed_s"], thermal_df["band_minus_c"], linestyle=":", label="Band -")
    ax.set_ylabel("Temp (C)")
    ax.legend(loc="upper right")
    add_phase_guides(ax, boundaries)

    # 2) Fan
    ax = axes[1]
    ax.plot(thermal_df["elapsed_s"], thermal_df["fan_pct"], label="Fan %")
    ax.set_ylabel("Fan (%)")
    ax.legend(loc="upper right")
    add_phase_guides(ax, boundaries)

    # 3) SM Clock drop
    ax = axes[2]
    ax.plot(sm_df["elapsed_s"], sm_df["sm_clock_mhz"], label="SM Clock (MHz)")
    ax.set_ylabel("SM Clock (MHz)")
    ax.legend(loc="upper right")
    add_phase_guides(ax, boundaries)

    # 若你想看 raw MHz，可解除下面註解
    # ax2 = ax.twinx()
    # ax2.plot(sm_df["elapsed_s"], sm_df["sm_clock_mhz"], alpha=0.5, label="SM Clock (MHz)")
    # ax2.set_ylabel("SM Clock (MHz)")

    # 4) Latency
    ax = axes[3]
    if latency_df is not None:
        if "server_ms" in latency_df.columns:
            ax.plot(
                latency_df["elapsed_s"],
                latency_df["server_ms"],
                label="Server Latency (ms)",
                linewidth=1.2,
            )
        ax.legend(loc="upper right")
    else:
        ax.text(
            0.5, 0.5,
            "No latency CSV found",
            ha="center", va="center",
            transform=ax.transAxes
        )
    ax.set_ylabel("Latency (ms)")
    ax.set_xlabel("Elapsed Seconds")
    add_phase_guides(ax, boundaries)

    if title:
        fig.suptitle(title)

    fig.savefig(output_path, dpi=150)
    print(f"saved: {output_path}")


# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="從既有 thermal / aligned / latency csv 重劃 Temp, Fan, SM Clock Drop, Latency 圖"
    )
    parser.add_argument("run_dir", help="實驗目錄，例如 ~/exp_runs/yolo26_icclz1_thermal_latency_01")
    parser.add_argument(
        "--output",
        help="輸出圖檔路徑，預設為 run_dir/replot_temp_fan_smclock_latency.png",
        default=None,
    )
    parser.add_argument("--title", help="圖標題", default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"run_dir 不存在: {run_dir}")

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else run_dir / "replot_temp_fan_smclock_latency.png"
    )

    thermal_df = extract_thermal(run_dir)
    sm_df = extract_smclock(run_dir)
    sm_df = compute_smclock_drop(sm_df, thermal_df)
    latency_df = extract_latency(run_dir)

    plot_all(
        thermal_df=thermal_df,
        sm_df=sm_df,
        latency_df=latency_df,
        output_path=output_path,
        title=args.title,
    )


if __name__ == "__main__":
    main()
