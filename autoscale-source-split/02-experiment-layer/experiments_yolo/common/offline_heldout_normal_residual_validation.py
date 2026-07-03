#!/usr/bin/env python3
"""Held-out normal residual false-alarm validation for open-loop baseline data."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd


FORBIDDEN_PRIMARY_FEATURES = {
    "phase",
    "fan_mode",
    "fan_speed",
    "intervention_flag",
    "t_rel_s",
    "run_id",
    "cycle_id",
    "profile_id",
    "absolute_elapsed_s",
    "elapsed_s",
    "manifest_replicate",
    "manifest_warmup_s",
    "manifest_created_at_utc",
}


def parse_csv_list(text: str) -> List[str]:
    return [c.strip() for c in text.split(",") if c.strip()]


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def q(values: Iterable[float], quantile: float) -> float | None:
    vals = [float(v) for v in values if math.isfinite(float(v))]
    if not vals:
        return None
    return float(np.quantile(vals, quantile))


def rmse(values: pd.Series) -> float:
    vals = pd.to_numeric(values, errors="coerce").dropna()
    if vals.empty:
        return float("nan")
    return float(np.sqrt(np.mean(np.square(vals))))


def mae(values: pd.Series) -> float:
    vals = pd.to_numeric(values, errors="coerce").dropna()
    if vals.empty:
        return float("nan")
    return float(vals.abs().mean())


def fmt_num(value: Any, digits: int = 3) -> str:
    out = safe_float(value)
    if out is None:
        return "NA"
    return f"{out:.{digits}f}"


def bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def robust_scale(values: pd.Series) -> Tuple[float, float]:
    vals = pd.to_numeric(values, errors="coerce").dropna()
    if vals.empty:
        return 0.0, 1.0
    med = float(vals.median())
    mad = float((vals - med).abs().median() * 1.4826)
    return med, mad if mad > 1e-9 else 1.0


def fit_linear(train: pd.DataFrame, features: List[str], target: str) -> Dict[str, Any]:
    y = pd.to_numeric(train[target], errors="coerce")
    if not features:
        y = y.dropna()
        if len(y) < 12:
            raise ValueError(f"insufficient rows for intercept-only {target}: {len(y)}")
        pred = pd.Series(float(y.mean()), index=y.index)
        resid = pd.Series(y.values - pred.values)
        center, scale = robust_scale(resid)
        return {
            "target": target,
            "features": [],
            "intercept": float(y.mean()),
            "coefficients": {},
            "feature_mean": {},
            "feature_std": {},
            "residual_center": center,
            "residual_scale": scale,
            "train_residual": resid,
            "model_type": "intercept_only",
        }
    x = train[features].apply(pd.to_numeric, errors="coerce")
    keep = x.notna().all(axis=1) & y.notna()
    x = x.loc[keep]
    y = y.loc[keep]
    if len(x) < max(12, len(features) + 3):
        raise ValueError(f"insufficient rows for {target}: {len(x)}")
    means = x.mean()
    stds = x.std().replace(0, 1.0)
    design = np.column_stack([np.ones(len(x)), ((x - means) / stds).values])
    coef, *_ = np.linalg.lstsq(design, y.values, rcond=None)
    pred = design @ coef
    resid = pd.Series(y.values - pred)
    center, scale = robust_scale(resid)
    return {
        "target": target,
        "features": features,
        "intercept": float(coef[0]),
        "coefficients": {f: float(c) for f, c in zip(features, coef[1:])},
        "feature_mean": means.to_dict(),
        "feature_std": stds.to_dict(),
        "residual_center": center,
        "residual_scale": scale,
        "train_residual": resid,
        "model_type": "linear",
    }


def predict(df: pd.DataFrame, model: Dict[str, Any]) -> pd.Series:
    features = list(model["features"])
    if not features:
        return pd.Series(float(model["intercept"]), index=df.index)
    x = df[features].apply(pd.to_numeric, errors="coerce")
    means = pd.Series(model["feature_mean"])
    stds = pd.Series(model["feature_std"]).replace(0, 1.0)
    z = (x - means) / stds
    pred = pd.Series(float(model["intercept"]), index=df.index)
    for feature, coef in model["coefficients"].items():
        pred = pred + z[feature] * float(coef)
    return pred


def manifest_replicate_map(df: pd.DataFrame) -> Tuple[Dict[str, Any], str | None]:
    if "manifest_replicate" not in df.columns:
        return {}, "manifest_replicate_column_missing"
    run_info = df[["run_id", "target_offered_rps", "manifest_replicate"]].drop_duplicates()
    if run_info["manifest_replicate"].isna().any() or (run_info["manifest_replicate"].astype(str).str.strip() == "").any():
        return {}, "manifest_replicate_missing_for_one_or_more_runs"
    if run_info.groupby("run_id")["manifest_replicate"].nunique().max() > 1:
        return {}, "manifest_replicate_not_unique_per_run"
    return {str(row["run_id"]): row["manifest_replicate"] for _, row in run_info.iterrows()}, None


def build_folds(df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    run_ids = sorted(str(x) for x in df["run_id"].dropna().unique())
    folds: List[Dict[str, Any]] = []
    split_notes: List[Dict[str, Any]] = []
    for run_id in run_ids:
        folds.append({"split": "leave_one_run_out", "fold": run_id, "test_runs": [run_id]})
    rep_map, gap = manifest_replicate_map(df)
    if gap:
        split_notes.append(
            {
                "split": "leave_one_replicate_per_load_level_out",
                "status": "skipped",
                "reason": gap,
                "note": "replicate split is not inferred from run_id ordering",
            }
        )
        return folds, split_notes
    for rep_id in sorted({str(v) for v in rep_map.values()}):
        test_runs = sorted(run for run, rep in rep_map.items() if str(rep) == rep_id)
        if test_runs:
            folds.append({"split": "leave_one_replicate_per_load_level_out", "fold": f"replicate_{rep_id}", "test_runs": test_runs})
    split_notes.append(
        {
            "split": "leave_one_replicate_per_load_level_out",
            "status": "enabled",
            "reason": "manifest_replicate_available",
            "note": "replicate identity read from manifest_replicate column",
        }
    )
    return folds, split_notes


def select_features(
    train: pd.DataFrame,
    requested: List[str],
    targets: List[str],
    fold_id: str,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    selected: List[str] = []
    for feature in requested:
        reason = ""
        if feature in FORBIDDEN_PRIMARY_FEATURES:
            reason = "forbidden_primary_feature"
        elif feature not in train.columns:
            reason = "missing_column"
        elif feature in targets:
            reason = "target_leakage_feature"
        else:
            vals = pd.to_numeric(train[feature], errors="coerce")
            non_missing = int(vals.notna().sum())
            missing_rate = 1.0 - non_missing / max(len(vals), 1)
            unique = int(vals.dropna().nunique())
            std = safe_float(vals.std())
            if non_missing < max(12, int(0.5 * len(vals))):
                reason = "too_many_missing_values"
            elif unique <= 1 or std is None or std < 1e-9:
                reason = "constant_or_near_constant_in_training_fold"
            else:
                selected.append(feature)
                reason = "selected"
        vals = pd.to_numeric(train[feature], errors="coerce") if feature in train.columns else pd.Series(dtype=float)
        rows.append(
            {
                "fold": fold_id,
                "feature": feature,
                "decision": reason,
                "train_rows": len(train),
                "non_missing": int(vals.notna().sum()) if feature in train.columns else 0,
                "missing_rate": float(1.0 - vals.notna().sum() / max(len(vals), 1)) if feature in train.columns else 1.0,
                "unique_count": int(vals.dropna().nunique()) if feature in train.columns else 0,
                "std": safe_float(vals.std()) if feature in train.columns else None,
            }
        )
    return selected, rows


def one_fold(
    df: pd.DataFrame,
    fold: Dict[str, Any],
    requested_features: List[str],
    targets: List[str],
    threshold_q: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], pd.DataFrame]:
    test_runs = set(fold["test_runs"])
    train = df[~df["run_id"].astype(str).isin(test_runs)].copy()
    test = df[df["run_id"].astype(str).isin(test_runs)].copy()
    fold_id = f"{fold['split']}::{fold['fold']}"
    selected_features, feature_rows = select_features(train, requested_features, targets, fold_id)
    if not selected_features:
        feature_rows.append(
            {
                "fold": fold_id,
                "feature": "__intercept_only__",
                "decision": "selected_intercept_only_all_requested_features_unusable",
                "train_rows": len(train),
                "non_missing": len(train),
                "missing_rate": 0.0,
                "unique_count": 1,
                "std": 0.0,
            }
        )

    thresholds: List[Dict[str, Any]] = []
    fold_metrics: List[Dict[str, Any]] = []
    run_metrics: List[Dict[str, Any]] = []
    scored_base_cols = [
        c
        for c in (
            "elapsed_s",
            "run_id",
            "target_offered_rps",
            "cooling_condition",
            "completion_completed_request_count",
            "completion_successful_completion_count",
            "completion_realized_completed_rps",
            "rolling_completion_count",
            "rolling_latency_sample_sufficient",
        )
        if c in test.columns
    ]
    scored = test[scored_base_cols].copy()
    risk_train_parts: List[pd.Series] = []
    risk_test_parts: List[pd.Series] = []

    for target in targets:
        model = fit_linear(train, selected_features, target)
        train_pred = predict(train, model)
        test_pred = predict(test, model)
        train_resid = pd.to_numeric(train[target], errors="coerce") - train_pred
        test_resid = pd.to_numeric(test[target], errors="coerce") - test_pred
        threshold = float(train_resid.abs().quantile(threshold_q))
        center, scale = robust_scale(train_resid)
        train_z = (train_resid - center) / scale
        test_z = (test_resid - center) / scale
        risk_train_parts.append(train_z.abs())
        risk_test_parts.append(test_z.abs())
        test_valid = test_resid.notna()
        train_valid = train_resid.notna()
        test_exceeds = test_resid.abs() > threshold
        scored[f"{target}_observed"] = pd.to_numeric(test[target], errors="coerce")
        scored[f"{target}_expected"] = test_pred
        scored[f"{target}_residual"] = test_resid
        scored[f"{target}_abs_residual"] = test_resid.abs()
        scored[f"{target}_exceeds_threshold"] = test_exceeds.where(test_valid, False)
        scored[f"{target}_valid_for_scoring"] = test_valid

        thresholds.append(
            {
                "split": fold["split"],
                "fold": fold["fold"],
                "target": target,
                "threshold_type": f"train_abs_residual_q{threshold_q}",
                "threshold": threshold,
                "train_residual_center": center,
                "train_residual_scale": scale,
                "features_used": ",".join(selected_features),
                "model_type": model.get("model_type"),
                "train_rows": int(train_valid.sum()),
                "test_rows": int(test_valid.sum()),
            }
        )
        fold_metrics.append(
            {
                "split": fold["split"],
                "fold": fold["fold"],
                "target": target,
                "test_runs": ",".join(fold["test_runs"]),
                "features_used_count": len(selected_features),
                "model_type": model.get("model_type"),
                "mae": mae(test_resid),
                "rmse": rmse(test_resid),
                "abs_residual_p50": q(test_resid.abs(), 0.50),
                "abs_residual_p95": q(test_resid.abs(), 0.95),
                "abs_residual_p99": q(test_resid.abs(), 0.99),
                "training_threshold": threshold,
                "valid_test_rows": int(test_valid.sum()),
                "threshold_exceedance_rate": float(test_exceeds[test_valid].mean()) if int(test_valid.sum()) else None,
                "false_alarms_per_healthy_hour": float(test_exceeds[test_valid].sum() / max(int(test_valid.sum()) / 3600.0, 1e-9)) if int(test_valid.sum()) else None,
            }
        )
        for run_id, part in scored.groupby("run_id"):
            resid = part[f"{target}_residual"]
            exceeds = part[f"{target}_exceeds_threshold"]
            valid = part[f"{target}_valid_for_scoring"].fillna(False).astype(bool)
            run_metrics.append(
                {
                    "split": fold["split"],
                    "fold": fold["fold"],
                    "run_id": run_id,
                    "target_offered_rps": float(part["target_offered_rps"].median()),
                    "target": target,
                    "rows": int(valid.sum()),
                    "mae": mae(resid),
                    "rmse": rmse(resid),
                    "abs_residual_p50": q(resid.abs(), 0.50),
                    "abs_residual_p95": q(resid.abs(), 0.95),
                    "abs_residual_p99": q(resid.abs(), 0.99),
                    "training_threshold": threshold,
                    "threshold_exceedance_rate": float(exceeds[valid].mean()) if int(valid.sum()) else None,
                    "false_alarms_per_healthy_hour": float(exceeds[valid].sum() / max(int(valid.sum()) / 3600.0, 1e-9)) if int(valid.sum()) else None,
                }
            )

    train_risk = pd.concat(risk_train_parts, axis=1).mean(axis=1)
    test_risk = pd.concat(risk_test_parts, axis=1).mean(axis=1)
    risk_threshold = float(train_risk.quantile(threshold_q))
    scored["composite_risk_score"] = test_risk
    scored["composite_risk_exceeds_threshold"] = test_risk > risk_threshold
    thresholds.append(
        {
            "split": fold["split"],
            "fold": fold["fold"],
            "target": "composite_risk_score",
            "threshold_type": f"train_composite_risk_q{threshold_q}",
            "threshold": risk_threshold,
            "features_used": ",".join(selected_features),
            "train_rows": len(train),
            "test_rows": len(test),
        }
    )
    for run_id, part in scored.groupby("run_id"):
        exceeds = part["composite_risk_exceeds_threshold"]
        run_metrics.append(
            {
                "split": fold["split"],
                "fold": fold["fold"],
                "run_id": run_id,
                "target_offered_rps": float(part["target_offered_rps"].median()),
                "target": "composite_risk_score",
                "rows": len(part),
                "abs_residual_p50": q(part["composite_risk_score"], 0.50),
                "abs_residual_p95": q(part["composite_risk_score"], 0.95),
                "abs_residual_p99": q(part["composite_risk_score"], 0.99),
                "training_threshold": risk_threshold,
                "threshold_exceedance_rate": float(exceeds.mean()),
                "false_alarms_per_healthy_hour": float(exceeds.sum() / max(len(part) / 3600.0, 1e-9)),
            }
        )
    fold_metrics.append(
        {
            "split": fold["split"],
            "fold": fold["fold"],
            "target": "composite_risk_score",
            "test_runs": ",".join(fold["test_runs"]),
            "features_used_count": len(selected_features),
            "abs_residual_p50": q(test_risk, 0.50),
            "abs_residual_p95": q(test_risk, 0.95),
            "abs_residual_p99": q(test_risk, 0.99),
            "training_threshold": risk_threshold,
            "threshold_exceedance_rate": float((test_risk > risk_threshold).mean()),
            "false_alarms_per_healthy_hour": float((test_risk > risk_threshold).sum() / max(len(test) / 3600.0, 1e-9)),
        }
    )
    scored.insert(0, "fold", fold["fold"])
    scored.insert(0, "split", fold["split"])
    return fold_metrics, run_metrics, thresholds, feature_rows, scored


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: List[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize_false_alarms(run_metrics: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["split", "target", "target_offered_rps"]
    rows = []
    for keys, part in run_metrics.groupby(group_cols, dropna=False):
        split, target, rps = keys
        rows.append(
            {
                "split": split,
                "target": target,
                "target_offered_rps": rps,
                "run_count": int(part["run_id"].nunique()),
                "median_false_alarms_per_healthy_hour": safe_float(part["false_alarms_per_healthy_hour"].median()),
                "p95_false_alarms_per_healthy_hour": safe_float(part["false_alarms_per_healthy_hour"].quantile(0.95)),
                "median_threshold_exceedance_rate": safe_float(part["threshold_exceedance_rate"].median()),
                "p95_abs_residual_median": safe_float(part["abs_residual_p95"].median()),
            }
        )
    return pd.DataFrame(rows)


def debounced_episode_summary(scored: pd.DataFrame, min_duration_s: int, refractory_s: int) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    exceed_cols = [c for c in scored.columns if c.endswith("_exceeds_threshold")]
    for (split, fold, run_id), part in scored.sort_values("elapsed_s").groupby(["split", "fold", "run_id"], dropna=False):
        elapsed = pd.to_numeric(part["elapsed_s"], errors="coerce").tolist()
        for col in exceed_cols:
            flags = bool_series(part[col]).tolist()
            episodes: List[Tuple[float, float]] = []
            start = None
            prev = None
            for flag, ts in zip(flags, elapsed):
                if not math.isfinite(float(ts)):
                    continue
                if flag and start is None:
                    start = float(ts)
                    prev = float(ts)
                elif flag:
                    prev = float(ts)
                elif start is not None:
                    episodes.append((start, prev if prev is not None else start))
                    start = None
                    prev = None
            if start is not None:
                episodes.append((start, prev if prev is not None else start))
            merged: List[Tuple[float, float]] = []
            for start_s, end_s in episodes:
                if end_s - start_s + 1 < min_duration_s:
                    continue
                if merged and start_s - merged[-1][1] <= refractory_s:
                    merged[-1] = (merged[-1][0], end_s)
                else:
                    merged.append((start_s, end_s))
            target = col.replace("_exceeds_threshold", "")
            rows.append(
                {
                    "split": split,
                    "fold": fold,
                    "run_id": run_id,
                    "target_offered_rps": safe_float(part["target_offered_rps"].median()),
                    "target": target,
                    "scored_rows": len(part),
                    "point_exceedance_count": int(sum(flags)),
                    "point_exceedance_rate_exploratory": float(sum(flags) / max(len(flags), 1)),
                    "episode_count": len(merged),
                    "episode_total_duration_s": sum(int(end - start + 1) for start, end in merged),
                    "episode_max_duration_s": max((int(end - start + 1) for start, end in merged), default=0),
                    "episodes": ";".join(f"{int(start)}-{int(end)}" for start, end in merged),
                    "min_episode_duration_s": min_duration_s,
                    "refractory_s": refractory_s,
                }
            )
    return pd.DataFrame(rows)


def feature_quality_notes(df: pd.DataFrame) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "gpu_util_pct" in df.columns and "vm_target_node_semantic__gpu_bound_features__gpu_compute__gpu_util_avg" in df.columns:
        nv = pd.to_numeric(df["gpu_util_pct"], errors="coerce")
        vm = pd.to_numeric(df["vm_target_node_semantic__gpu_bound_features__gpu_compute__gpu_util_avg"], errors="coerce")
        corr = nv.corr(vm)
        diff_med = (nv - vm).abs().median()
        out["nvidia_smi_vs_vm_gpu_util_corr"] = None if pd.isna(corr) else float(corr)
        out["nvidia_smi_vs_vm_gpu_util_abs_diff_median"] = None if pd.isna(diff_med) else float(diff_med)
    return out


def make_plots(out_dir: Path, run_metrics: pd.DataFrame, fold_metrics: pd.DataFrame) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    comp = run_metrics[run_metrics["target"] == "composite_risk_score"].copy()
    if not comp.empty:
        plt.figure(figsize=(8, 4))
        comp.boxplot(column="false_alarms_per_healthy_hour", by="target_offered_rps")
        plt.title("Held-out normal composite false alarms by offered RPS")
        plt.suptitle("")
        plt.xlabel("offered RPS")
        plt.ylabel("false alarms / healthy hour")
        plt.tight_layout()
        plt.savefig(fig_dir / "composite_false_alarms_by_offered_rps.png", dpi=160)
        plt.close()
    target_part = fold_metrics[fold_metrics["target"].isin(["gpu_temp_c", "sm_clock_mhz", "completion_latency_p95", "rolling_latency_p95"])].copy()
    if not target_part.empty:
        plt.figure(figsize=(9, 4))
        labels = []
        values = []
        for target, part in target_part.groupby("target"):
            labels.append(target)
            values.append(float(part["threshold_exceedance_rate"].median()))
        plt.bar(labels, values)
        plt.ylabel("median held-out exceedance rate")
        plt.xticks(rotation=20, ha="right")
        plt.tight_layout()
        plt.savefig(fig_dir / "target_exceedance_rate_summary.png", dpi=160)
        plt.close()


def write_report(
    out_dir: Path,
    dataset: Path,
    manifest: Dict[str, Any],
    fold_metrics: pd.DataFrame,
    run_metrics: pd.DataFrame,
    false_alarm_summary: pd.DataFrame,
    episode_summary: pd.DataFrame,
    quality: Dict[str, Any],
) -> None:
    comp = false_alarm_summary[false_alarm_summary["target"] == "composite_risk_score"]
    max_comp_fa = float(comp["median_false_alarms_per_healthy_hour"].max()) if not comp.empty else float("nan")
    top_comp_rps = None
    if not comp.empty:
        top_row = comp.sort_values("median_false_alarms_per_healthy_hour", ascending=False).iloc[0]
        top_comp_rps = safe_float(top_row.get("target_offered_rps"))
    target_exceed = fold_metrics[fold_metrics["target"] != "composite_risk_score"]["threshold_exceedance_rate"]
    median_target_exceed = float(target_exceed.median()) if not target_exceed.empty else float("nan")
    conclusions: List[str] = []
    if manifest["runs"] < 9:
        conclusions.append("insufficient normal replicates")
    comp_eps = episode_summary[episode_summary["target"] == "composite_risk"] if not episode_summary.empty else pd.DataFrame()
    max_comp_episodes = int(comp_eps["episode_count"].max()) if not comp_eps.empty else 0
    if max_comp_episodes > 0 or max_comp_fa > 120 or median_target_exceed > 0.10:
        conclusions.append("residual baseline unstable across runs")
    if quality.get("nvidia_smi_vs_vm_gpu_util_corr") is not None and abs(float(quality["nvidia_smi_vs_vm_gpu_util_corr"])) < 0.3:
        conclusions.append("feature quality issue")
    if not conclusions and manifest["runs"] >= 9:
        conclusions.append("held-out normal residual baseline verified")
    if not conclusions:
        conclusions.append("no conclusion yet")

    comp_by_rps = comp.sort_values("target_offered_rps") if not comp.empty else pd.DataFrame()
    comp_fa_values = comp_by_rps["median_false_alarms_per_healthy_hour"].tolist() if not comp_by_rps.empty else []
    systematic_note = "not evaluated"
    if comp_fa_values:
        increasing = all(a <= b for a, b in zip(comp_fa_values, comp_fa_values[1:]))
        if increasing:
            systematic_note = "composite false alarms increase with offered_rps"
        elif top_comp_rps is not None:
            systematic_note = f"highest composite false alarms appear at offered_rps={top_comp_rps}; not monotonic with load"

    lines = [
        "# Held-out normal residual validation",
        "",
        f"- dataset: `{dataset}`",
        f"- created_at_utc: `{datetime.now(timezone.utc).isoformat()}`",
        f"- runs: `{manifest['runs']}`",
        f"- rows: `{manifest['rows']}`",
        f"- folds: `{manifest['folds']}`",
        f"- split notes: `{manifest.get('split_notes')}`",
        f"- threshold quantile: `{manifest['threshold_quantile']}`",
        f"- conclusion: `{'; '.join(conclusions)}`",
        f"- formal episode max composite count per held-out run: `{max_comp_episodes}`",
        "",
        "## 結論分類",
        "",
        *[f"- `{item}`" for item in conclusions],
        "",
        "這份 validation 使用 run-level holdout，不使用 random row split，也不讓同一 run 的相鄰時間點跨 train/test。threshold、residual center/scale 與 feature availability 皆只由 training normal-cooling runs 決定。",
        "Leave-one-replicate-per-load-level split 只在 manifest 真的提供 replicate identity 時啟用；本工具不再用 run_id 排序推估 replicate。",
        "正式結論以 debounced anomaly episodes 為主；point-wise exceedance / FA per hour 只保留為 short-run sensitivity comparison。",
        "",
        "## Load-Level Pattern",
        "",
        f"- composite risk offered-RPS pattern: {systematic_note}",
        f"- max median composite false alarms per healthy hour: `{max_comp_fa}`",
        f"- median target exceedance rate across held-out folds: `{median_target_exceed}`",
        "",
        "## False Alarm Summary",
        "",
        "| split | target | offered_rps | runs | median FA/h | median exceedance |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in false_alarm_summary.to_dict("records"):
        lines.append(
            f"| `{row['split']}` | `{row['target']}` | {row['target_offered_rps']} | {row['run_count']} | "
            f"{fmt_num(row['median_false_alarms_per_healthy_hour'], 3)} | {fmt_num(row['median_threshold_exceedance_rate'], 4)} |"
        )
    lines.extend(
        [
            "",
            "## Debounced Episode Summary",
            "",
            "| target | offered_rps | runs | total episodes | median point exceedance sensitivity |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    if not episode_summary.empty:
        eps = episode_summary.groupby(["target", "target_offered_rps"], dropna=False).agg(
            runs=("run_id", "nunique"),
            total_episodes=("episode_count", "sum"),
            median_point_exceedance=("point_exceedance_rate_exploratory", "median"),
        ).reset_index()
        for row in eps.to_dict("records"):
            lines.append(
                f"| `{row['target']}` | {row['target_offered_rps']} | {row['runs']} | {row['total_episodes']} | {fmt_num(row['median_point_exceedance'], 4)} |"
            )
    lines.extend(
        [
            "",
            "## Feature Quality",
            "",
            f"- nvidia-smi vs VM GPU util corr: `{quality.get('nvidia_smi_vs_vm_gpu_util_corr')}`",
            f"- nvidia-smi vs VM GPU util median abs diff: `{quality.get('nvidia_smi_vs_vm_gpu_util_abs_diff_median')}`",
            f"- VM gpu_util feature present in dataset: `{'vm_target_node_semantic__gpu_bound_features__gpu_compute__gpu_util_avg' in manifest.get('dataset_columns', [])}`",
            "",
            "若 feature quality issue 出現，下一步模型應避免把該 VM GPU util 欄位作為 primary feature，並以 nvidia-smi/DCGM 交叉驗證。",
            "",
            "## Interpretation",
            "",
            "- Observed directly: replicated normal runs 可用於 held-out false-alarm validation。",
            "- Strong temporal/statistical evidence: normal residual threshold 必須用 held-out run 檢查，不能只看 in-sample residual。",
            "- Inconclusive: 尚未驗證 cooling-constrained condition，也尚未證明未知根因泛化。",
        ]
    )
    text = "\n".join(lines) + "\n"
    (out_dir / "HELDOUT_NORMAL_RESIDUAL_VALIDATION.md").write_text(text, encoding="utf-8")
    (out_dir / "final_report_zh.md").write_text(text, encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    out_dir = Path(args.out_dir)
    df = pd.read_csv(dataset)
    if "eligible_for_formal_validation" in df.columns:
        before = len(df)
        df = df[bool_series(df["eligible_for_formal_validation"])].copy()
        if df.empty:
            raise RuntimeError(f"no manifest-valid measurement-window rows available for formal validation; input rows={before}")
    features = parse_csv_list(args.load_cols)
    targets = parse_csv_list(args.target_cols)
    required = ["run_id", "target_offered_rps", "cooling_condition"] + targets
    missing = [c for c in required if c not in df.columns]
    forbidden = sorted(set(features) & FORBIDDEN_PRIMARY_FEATURES)
    if "target_offered_rps" in features and "scheduled_request_count" in features:
        raise RuntimeError("feature schema violation: target_offered_rps and scheduled_request_count must not both be primary predictors")
    if missing:
        raise RuntimeError(f"missing required columns: {missing}")
    if forbidden:
        raise RuntimeError(f"forbidden primary features requested: {forbidden}")
    folds, split_notes = build_folds(df)
    out_dir.mkdir(parents=True, exist_ok=True)

    fold_rows: List[Dict[str, Any]] = []
    run_rows: List[Dict[str, Any]] = []
    threshold_rows: List[Dict[str, Any]] = []
    feature_rows: List[Dict[str, Any]] = []
    scored_parts: List[pd.DataFrame] = []
    for fold in folds:
        fm, rm, th, fr, scored = one_fold(df, fold, features, targets, args.threshold_quantile)
        fold_rows.extend(fm)
        run_rows.extend(rm)
        threshold_rows.extend(th)
        feature_rows.extend(fr)
        scored_parts.append(scored)

    write_csv(out_dir / "heldout_normal_residual_fold_metrics.csv", fold_rows)
    write_csv(out_dir / "heldout_normal_residual_run_metrics.csv", run_rows)
    write_csv(out_dir / "heldout_normal_thresholds.csv", threshold_rows)
    write_csv(out_dir / "heldout_normal_feature_availability.csv", feature_rows)
    scored_df = pd.concat(scored_parts, ignore_index=True)
    scored_df.to_csv(out_dir / "heldout_normal_scored_timeline.csv", index=False)
    fold_df = pd.DataFrame(fold_rows)
    run_df = pd.DataFrame(run_rows)
    false_alarm_summary = summarize_false_alarms(run_df)
    false_alarm_summary.to_csv(out_dir / "heldout_normal_false_alarm_summary.csv", index=False)
    episode_summary = debounced_episode_summary(scored_df, args.min_episode_duration_s, args.refractory_s)
    episode_summary.to_csv(out_dir / "heldout_normal_debounced_episode_summary.csv", index=False)
    quality = feature_quality_notes(df)
    manifest = {
        "dataset": str(dataset),
        "rows": int(len(df)),
        "runs": int(df["run_id"].nunique()),
        "folds": len(folds),
        "threshold_quantile": args.threshold_quantile,
        "features_requested": features,
        "targets": targets,
        "formal_rows_after_measurement_eligibility_filter": int(len(df)),
        "min_episode_duration_s": args.min_episode_duration_s,
        "refractory_s": args.refractory_s,
        "split_strategies": sorted(set(f["split"] for f in folds)),
        "split_notes": split_notes,
        "feature_quality": quality,
        "dataset_columns": list(df.columns),
        "no_random_row_split": True,
        "no_phase_fan_intervention_features": True,
    }
    write_csv(out_dir / "heldout_normal_split_notes.csv", split_notes)
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    make_plots(out_dir, run_df, fold_df)
    write_report(out_dir, dataset, manifest, fold_df, run_df, false_alarm_summary, episode_summary, quality)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--load-cols", required=True)
    p.add_argument("--target-cols", default="gpu_temp_c,sm_clock_mhz,completion_latency_p95")
    p.add_argument("--threshold-quantile", type=float, default=0.99)
    p.add_argument("--min-episode-duration-s", type=int, default=3)
    p.add_argument("--refractory-s", type=int, default=5)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
