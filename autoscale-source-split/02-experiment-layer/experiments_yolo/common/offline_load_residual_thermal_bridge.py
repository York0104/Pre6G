#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


DEFAULT_RESULTS_ROOT = Path(
    "autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle"
)
DEFAULT_LOAD_DIR = DEFAULT_RESULTS_ROOT / "vm_load_forecasting_analysis"
DEFAULT_THERMAL_DIR = DEFAULT_RESULTS_ROOT / "offline_forecasting_analysis"
DEFAULT_OUT_NAME = "load_residual_thermal_bridge_analysis"
LOAD_TARGETS = ["gpu_util_percent", "vram_used_percent", "cpu_usage_percent", "ram_usage_percent"]
LOAD_FORECAST_HORIZON_S = 30
WARNING_HORIZON_S = 30
DEGRADATION_SUSTAIN_WINDOW_S = 15
DEGRADATION_MIN_BAD_SECONDS = 5


def chrono_split(run_ids: list[str]) -> tuple[list[str], list[str]]:
    ordered = sorted(run_ids)
    n_test = max(1, int(math.ceil(len(ordered) * 0.2)))
    return ordered[:-n_test], ordered[-n_test:]


def q(s: pd.Series, p: float) -> float:
    v = pd.to_numeric(s, errors="coerce").dropna()
    return float(v.quantile(p)) if len(v) else math.nan


def mad(s: pd.Series) -> float:
    v = pd.to_numeric(s, errors="coerce").dropna()
    if len(v) == 0:
        return math.nan
    med = v.median()
    return float((v - med).abs().median())


def add_load_forecast_residuals(load_df: pd.DataFrame, train_runs: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_cols = []
    for col in LOAD_TARGETS:
        for candidate in load_df.columns:
            if candidate == col or candidate.startswith(f"{col}_lag_") or candidate.startswith(f"{col}_roll_") or candidate.startswith(f"{col}_slope_"):
                feature_cols.append(candidate)
    feature_cols = sorted(set(feature_cols))
    rows = []
    residual_frames = []
    for target in LOAD_TARGETS:
        work = load_df.copy()
        work["origin_elapsed_s"] = pd.to_numeric(work["elapsed_s"], errors="coerce")
        work["y_future"] = work.groupby("run_id", group_keys=False)[target].shift(-LOAD_FORECAST_HORIZON_S)
        model_df = work.dropna(subset=["run_id", "origin_elapsed_s", target, "y_future"])
        train = model_df[model_df["run_id"].isin(train_runs)]
        if len(train) < 100:
            rows.append({"target": target, "model": "insufficient_data", "train_rows": len(train)})
            continue
        X_train = train[feature_cols]
        y_train = train["y_future"]
        models = {
            "linear_ar_ridge": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0)),
            "hist_gradient_boosting": make_pipeline(
                SimpleImputer(strategy="median"),
                HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, l2_regularization=0.1, random_state=13),
            ),
        }
        best_name = ""
        best_mae = math.inf
        best_pred = None
        for name, model in models.items():
            model.fit(X_train, y_train)
            pred_train = model.predict(X_train)
            mae = float(np.mean(np.abs(y_train.to_numpy() - pred_train)))
            rows.append({"target": target, "model": name, "train_rows": len(train), "train_mae": mae})
            if mae < best_mae:
                best_mae = mae
                best_name = name
                best_pred = model.predict(model_df[feature_cols])
        if best_pred is None:
            continue
        out = model_df[["run_id", "origin_elapsed_s", target, "y_future"]].copy()
        out["residual_elapsed_s"] = (out["origin_elapsed_s"] + LOAD_FORECAST_HORIZON_S).round().astype("Int64")
        out[f"{target}_forecast_h{LOAD_FORECAST_HORIZON_S}s"] = best_pred
        out[f"{target}_residual_h{LOAD_FORECAST_HORIZON_S}s"] = out["y_future"] - best_pred
        out[f"{target}_abs_residual_h{LOAD_FORECAST_HORIZON_S}s"] = out[f"{target}_residual_h{LOAD_FORECAST_HORIZON_S}s"].abs()
        out["target"] = target
        out["load_model"] = best_name
        residual_frames.append(out)
    if not residual_frames:
        return pd.DataFrame(), pd.DataFrame(rows)
    merged = None
    for frame in residual_frames:
        target = frame["target"].iloc[0]
        cols = [
            "run_id",
            "residual_elapsed_s",
            f"{target}_forecast_h{LOAD_FORECAST_HORIZON_S}s",
            f"{target}_residual_h{LOAD_FORECAST_HORIZON_S}s",
            f"{target}_abs_residual_h{LOAD_FORECAST_HORIZON_S}s",
        ]
        small = frame[cols].copy()
        merged = small if merged is None else merged.merge(small, on=["run_id", "residual_elapsed_s"], how="outer")
    assert merged is not None
    return merged.rename(columns={"residual_elapsed_s": "elapsed_s_round"}), pd.DataFrame(rows)


def build_composite_label(df: pd.DataFrame, train_runs: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
    train = out[out["run_id"].isin(train_runs)]
    healthy = train[
        train["phase"].astype(str).eq("normal_hold")
        & train["success_rate"].fillna(0).ge(0.95)
        & train["fail_rate"].fillna(1).le(0.05)
        & train["timeout_error_rate"].fillna(1).le(0.05)
    ]
    if len(healthy) < 100:
        healthy = train[train["phase"].astype(str).eq("normal_hold")]
    lat = pd.to_numeric(healthy["server_total_latency_ms_med"], errors="coerce")
    latency_threshold = max(q(lat, 0.95), float(lat.median() + 6.0 * mad(lat)))
    success_low = min(0.95, q(healthy["success_rate"], 0.05))
    fail_high = max(0.2, q(healthy["fail_rate"], 0.95))
    timeout_high = max(0.2, q(healthy["timeout_error_rate"], 0.95))
    instant = (
        pd.to_numeric(out["server_total_latency_ms_med"], errors="coerce").gt(latency_threshold)
        | pd.to_numeric(out["success_rate"], errors="coerce").lt(success_low)
        | pd.to_numeric(out["fail_rate"], errors="coerce").gt(fail_high)
        | pd.to_numeric(out["timeout_error_rate"], errors="coerce").gt(timeout_high)
    )
    out["instant_service_degraded_now"] = instant.astype(int)
    out["service_degraded_now"] = (
        out.groupby("run_id", group_keys=False)["instant_service_degraded_now"]
        .transform(lambda s: s.rolling(DEGRADATION_SUSTAIN_WINDOW_S, min_periods=1).sum().ge(DEGRADATION_MIN_BAD_SECONDS))
        .astype(int)
    )
    out["actual_future_degradation"] = (
        out.groupby("run_id", group_keys=False)["service_degraded_now"]
        .transform(lambda s: s.shift(-1).rolling(WARNING_HORIZON_S, min_periods=1).max().shift(-(WARNING_HORIZON_S - 1)))
        .fillna(0)
        .astype(int)
    )
    thresholds = pd.DataFrame(
        [
            {
                "latency_threshold_ms": latency_threshold,
                "success_rate_low_threshold": success_low,
                "fail_rate_high_threshold": fail_high,
                "timeout_rate_high_threshold": timeout_high,
                "healthy_rows": len(healthy),
                "train_runs": ",".join(train_runs),
            }
        ]
    )
    return out, thresholds


def first_onsets(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (run_id, cycle_uid), g in df.sort_values("t_rel_s").groupby(["run_id", "cycle_uid"]):
        degraded = g[g["service_degraded_now"].eq(1)]
        if degraded.empty:
            continue
        rows.append(
            {
                "run_id": run_id,
                "cycle_uid": cycle_uid,
                "degradation_onset_s": float(degraded["t_rel_s"].iloc[0]),
            }
        )
    return pd.DataFrame(rows)


def evaluate_feature_sets(df: pd.DataFrame, train_runs: list[str], test_runs: list[str], out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    thermal_features = [
        c
        for c in [
            "gpu_temp_c",
            "gpu_temp_c_delta",
            "gpu_temp_c_slope_5s",
            "gpu_temp_c_slope_15s",
            "gpu_clock_mhz",
            "gpu_clock_mhz_delta",
            "gpu_clock_mhz_slope_5s",
            "gpu_clock_mhz_slope_15s",
            "gpu_mem_clock_mhz",
            "gpu_power_w",
            "gpu_util_pct",
        ]
        if c in df.columns
    ]
    load_features = []
    for target in LOAD_TARGETS:
        for suffix in ["residual", "abs_residual", "forecast"]:
            col = f"{target}_{suffix}_h{LOAD_FORECAST_HORIZON_S}s"
            if col in df.columns:
                load_features.append(col)
    feature_sets = {
        "thermal_only": thermal_features,
        "load_residual_only": load_features,
        "thermal_plus_load_residual": thermal_features + load_features,
    }
    train_base = df[df["run_id"].isin(train_runs) & df["service_degraded_now"].eq(0)].copy()
    test_base = df[df["run_id"].isin(test_runs) & df["service_degraded_now"].eq(0)].copy()
    rows = []
    timelines = []
    coefs = []
    for set_name, features in feature_sets.items():
        train = train_base.dropna(subset=["actual_future_degradation"])
        test = test_base.dropna(subset=["actual_future_degradation"])
        if not features or train["actual_future_degradation"].nunique() < 2 or test["actual_future_degradation"].nunique() < 2:
            rows.append(
                {
                    "feature_set": set_name,
                    "status": "insufficient_class_diversity_or_features",
                    "feature_count": len(features),
                    "train_rows": len(train),
                    "test_rows": len(test),
                    "train_positive_rate": float(train["actual_future_degradation"].mean()) if len(train) else math.nan,
                    "test_positive_rate": float(test["actual_future_degradation"].mean()) if len(test) else math.nan,
                }
            )
            continue
        model = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(max_iter=1000, class_weight="balanced", C=1.0),
        )
        model.fit(train[features], train["actual_future_degradation"])
        train_score = model.predict_proba(train[features])[:, 1]
        test_score = model.predict_proba(test[features])[:, 1]
        precision, recall, thresholds = precision_recall_curve(train["actual_future_degradation"], train_score)
        f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
        if len(thresholds):
            idx = int(np.nanargmax(f1[:-1])) if len(f1) > 1 else 0
            threshold = float(thresholds[min(idx, len(thresholds) - 1)])
        else:
            threshold = 0.5
        pred = (test_score >= threshold).astype(int)
        rows.append(
            {
                "feature_set": set_name,
                "status": "ok",
                "feature_count": len(features),
                "train_rows": len(train),
                "test_rows": len(test),
                "train_positive_rate": float(train["actual_future_degradation"].mean()),
                "test_positive_rate": float(test["actual_future_degradation"].mean()),
                "threshold_from_train": threshold,
                "precision": float(precision_score(test["actual_future_degradation"], pred, zero_division=0)),
                "recall": float(recall_score(test["actual_future_degradation"], pred, zero_division=0)),
                "balanced_accuracy": float(balanced_accuracy_score(test["actual_future_degradation"], pred)),
                "pr_auc": float(average_precision_score(test["actual_future_degradation"], test_score)),
                "warning_rate": float(pred.mean()),
            }
        )
        tl = test[["run_id", "cycle_uid", "client_ts", "t_rel_s", "phase", "service_degraded_now", "actual_future_degradation"]].copy()
        tl["feature_set"] = set_name
        tl["warning_score"] = test_score
        tl["warning"] = pred
        timelines.append(tl)
        lr = model.named_steps["logisticregression"]
        for feat, coef in sorted(zip(features, lr.coef_[0]), key=lambda x: abs(x[1]), reverse=True):
            coefs.append(
                {
                    "feature_set": set_name,
                    "feature": feat,
                    "coefficient": float(coef),
                    "abs_coefficient": float(abs(coef)),
                }
            )
    eval_df = pd.DataFrame(rows)
    timeline_df = pd.concat(timelines, ignore_index=True) if timelines else pd.DataFrame()
    coef_df = pd.DataFrame(coefs)
    eval_df.to_csv(out_dir / "early_warning_feature_set_comparison.csv", index=False)
    timeline_df.to_csv(out_dir / "early_warning_feature_set_timeline.csv", index=False)
    coef_df.to_csv(out_dir / "early_warning_feature_set_coefficients.csv", index=False)
    return eval_df, timeline_df, coef_df


def residual_event_study(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    onsets = first_onsets(df)
    if onsets.empty:
        out = pd.DataFrame()
        out.to_csv(out_dir / "load_residual_event_study.csv", index=False)
        return out
    merged = df.merge(onsets, on=["run_id", "cycle_uid"], how="inner")
    merged["rel_to_degradation_onset_s"] = merged["t_rel_s"] - merged["degradation_onset_s"]
    bins = [(-120, -60), (-60, -30), (-30, 0), (0, 30), (30, 60), (60, 120)]
    rows = []
    for lo, hi in bins:
        w = merged[merged["rel_to_degradation_onset_s"].ge(lo) & merged["rel_to_degradation_onset_s"].lt(hi)]
        row = {"window": f"{lo}_to_{hi}s", "rows": len(w)}
        for target in LOAD_TARGETS:
            col = f"{target}_abs_residual_h{LOAD_FORECAST_HORIZON_S}s"
            if col in w:
                row[f"{target}_abs_residual_median"] = float(pd.to_numeric(w[col], errors="coerce").median())
                row[f"{target}_abs_residual_p90"] = float(pd.to_numeric(w[col], errors="coerce").quantile(0.9))
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "load_residual_event_study.csv", index=False)
    return out


def plots(df: pd.DataFrame, event_df: pd.DataFrame, eval_df: pd.DataFrame, timeline: pd.DataFrame, out_dir: Path) -> None:
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(exist_ok=True)
    if not event_df.empty:
        fig, ax = plt.subplots(figsize=(12, 5))
        x = np.arange(len(event_df))
        width = 0.18
        for i, target in enumerate(LOAD_TARGETS):
            col = f"{target}_abs_residual_median"
            if col in event_df:
                ax.bar(x + (i - 1.5) * width, event_df[col], width, label=target)
        ax.set_xticks(x)
        ax.set_xticklabels(event_df["window"], rotation=30, ha="right")
        ax.set_ylabel("median absolute residual")
        ax.set_title("Load forecast residual around service degradation onset")
        ax.grid(axis="y", alpha=0.25)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(fig_dir / "load_residual_event_study.png", dpi=170)
        plt.close(fig)
    ok_eval = eval_df[eval_df["status"].eq("ok")] if "status" in eval_df else pd.DataFrame()
    if not ok_eval.empty:
        fig, ax = plt.subplots(figsize=(9, 4))
        ok_eval.set_index("feature_set")[["precision", "recall", "balanced_accuracy", "pr_auc"]].plot(kind="bar", ax=ax)
        ax.set_ylim(0, 1.05)
        ax.set_title("Early-warning comparison by feature set")
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(fig_dir / "early_warning_feature_set_comparison.png", dpi=170)
        plt.close(fig)
    if not timeline.empty:
        run_id = sorted(timeline["run_id"].unique())[-1]
        d = timeline[timeline["run_id"].eq(run_id)].copy()
        fig, ax = plt.subplots(figsize=(13, 5))
        for fs, g in d.groupby("feature_set"):
            ax.plot(g["t_rel_s"], g["warning_score"], lw=1.0, label=fs)
        degraded = d.groupby("t_rel_s")["actual_future_degradation"].max()
        ax.fill_between(degraded.index, 0, degraded.values, color="tab:red", alpha=0.12, label="future degradation label")
        ax.set_xlabel("cycle relative seconds")
        ax.set_ylabel("warning score")
        ax.set_title(f"Held-out warning score timeline: {run_id}")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(fig_dir / "heldout_warning_score_timeline.png", dpi=170)
        plt.close(fig)


def md_table(df: pd.DataFrame, cols: list[str]) -> str:
    if df.empty:
        return ""
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in df[cols].itertuples(index=False):
        vals = []
        for v in row:
            vals.append(f"{v:.6g}" if isinstance(v, float) else str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def write_report(out_dir: Path, train_runs: list[str], test_runs: list[str], thresholds: pd.DataFrame, eval_df: pd.DataFrame, event_df: pd.DataFrame) -> None:
    lines = [
        "# Load Residual 接續 Thermal Degradation Early-Warning 實驗",
        "",
        "## 實驗設計",
        "",
        f"- load forecast horizon：{LOAD_FORECAST_HORIZON_S} 秒。",
        f"- early-warning horizon：{WARNING_HORIZON_S} 秒。",
        "- residual 可用時間：使用 t-H 做出的 forecast 與 t 時刻觀測值形成 residual，避免把 t+H 真值反向滲入 t 時刻 feature。",
        "- split：chronological group split by RUN_ID；同一 run 不跨 train/test；未使用 random row split。",
        "- primary feature sets：thermal-only、load-residual-only、thermal+load-residual。",
        "- control metadata：未使用 phase、fan mode、intervention flag、run_id、cycle_id 作模型 feature。",
        "",
        "## Train / Test runs",
        "",
        f"- train：{', '.join(train_runs)}",
        f"- test：{', '.join(test_runs)}",
        "",
        "## Composite degradation threshold",
        "",
        md_table(thresholds, thresholds.columns.tolist()),
        "",
        "## Early-warning feature set comparison",
        "",
    ]
    if eval_df.empty:
        lines.append("資料不足，無法評估。")
    else:
        cols = [
            "feature_set",
            "status",
            "feature_count",
            "train_rows",
            "test_rows",
            "test_positive_rate",
            "precision",
            "recall",
            "balanced_accuracy",
            "pr_auc",
            "warning_rate",
        ]
        cols = [c for c in cols if c in eval_df.columns]
        lines.append(md_table(eval_df, cols))
    lines.extend(["", "## Load residual event study", ""])
    if event_df.empty:
        lines.append("沒有可對齊的 degradation onset。")
    else:
        lines.append(md_table(event_df, event_df.columns.tolist()))
    lines.extend(
        [
            "",
            "## 解讀限制",
            "",
            "- 本實驗檢查負載 forecast residual 是否能作為 thermal-performance degradation 的前置訊號。",
            "- 目前資料多來自同一 fan-cycle template，因此若結果很好，仍需警惕固定流程與固定 onset 時序。",
            "- load residual 是可部署方向的候選訊號，但還需要純正常高負載、不同 workload intensity、open-loop request 等資料驗證泛化。",
        ]
    )
    (out_dir / "load_residual_thermal_bridge_report_zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/pre6g_matplotlib")
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    ap.add_argument("--load-dir", type=Path, default=DEFAULT_LOAD_DIR)
    ap.add_argument("--thermal-dir", type=Path, default=DEFAULT_THERMAL_DIR)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()
    out_dir = args.out_dir or (args.results_root / DEFAULT_OUT_NAME)
    out_dir.mkdir(parents=True, exist_ok=True)

    load_df = pd.read_csv(args.load_dir / "vm_load_aligned_features.csv", low_memory=False)
    thermal_df = pd.read_csv(args.thermal_dir / "aligned_multirun_1s_with_features.csv", low_memory=False)
    load_df["elapsed_s_round"] = pd.to_numeric(load_df["elapsed_s"], errors="coerce").round().astype("Int64")
    thermal_df["elapsed_s_round"] = pd.to_numeric(thermal_df["elapsed_s"], errors="coerce").round().astype("Int64")
    run_ids = sorted(set(load_df["run_id"].dropna()).intersection(set(thermal_df["run_id"].dropna())))
    train_runs, test_runs = chrono_split(run_ids)

    residuals, load_model_eval = add_load_forecast_residuals(load_df[load_df["run_id"].isin(run_ids)].copy(), train_runs)
    load_model_eval.to_csv(out_dir / "load_forecast_models_for_residuals.csv", index=False)
    bridge = thermal_df[thermal_df["run_id"].isin(run_ids)].merge(residuals, on=["run_id", "elapsed_s_round"], how="left")
    bridge, thresholds = build_composite_label(bridge, train_runs)
    bridge.to_csv(out_dir / "thermal_load_residual_bridge_dataset.csv", index=False)
    thresholds.to_csv(out_dir / "composite_degradation_thresholds.csv", index=False)
    event_df = residual_event_study(bridge, out_dir)
    eval_df, timeline, coef_df = evaluate_feature_sets(bridge, train_runs, test_runs, out_dir)
    plots(bridge, event_df, eval_df, timeline, out_dir)
    write_report(out_dir, train_runs, test_runs, thresholds, eval_df, event_df)
    manifest = {
        "analysis_name": "offline_load_residual_thermal_bridge",
        "load_forecast_horizon_s": LOAD_FORECAST_HORIZON_S,
        "warning_horizon_s": WARNING_HORIZON_S,
        "train_runs": train_runs,
        "test_runs": test_runs,
        "no_random_row_split": True,
        "future_leakage_controls": [
            "load residual timestamp is forecast origin plus horizon",
            "early-warning features use current or past-observable values only",
            "composite label thresholds are derived from training runs only",
            "control metadata excluded from primary model features",
        ],
        "outputs": sorted(str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file()),
    }
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] wrote load residual thermal bridge analysis to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
