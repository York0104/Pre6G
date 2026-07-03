#!/usr/bin/env python3
"""Load-conditioned expected behavior and residual bridge analysis.

The intended training set is normal_cooling open-loop runs only.  Cooling-
constrained runs are evaluated as OOD/anomaly conditions at comparable offered
load.  This script avoids phase/fan/run/cycle/time identifiers as primary
features.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

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
}


def robust_z(values: pd.Series, center: float, scale: float) -> pd.Series:
    denom = scale if scale > 1e-9 else 1.0
    return (values - center) / denom


def write_status(out_dir: Path, status: Dict[str, object]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    status["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    (out_dir / "analysis_status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    report = [
        "# Load-conditioned residual bridge analysis",
        "",
        f"- status: `{status.get('status')}`",
        f"- dataset: `{status.get('dataset')}`",
        f"- reason: {status.get('reason', '')}",
        "",
        "此分析只應使用 normal_cooling 訓練 expected behavior；cooling_constrained 僅作為 residual/anomaly 評估。",
    ]
    gaps = status.get("missing_columns") or []
    if gaps:
        report.extend(["", "## Missing Columns", ""])
        report.extend([f"- `{c}`" for c in gaps])
    (out_dir / "load_conditioned_residual_report_zh.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def fit_linear_expected(train: pd.DataFrame, features: List[str], target: str) -> Dict[str, object]:
    x = train[features].astype(float).replace([np.inf, -np.inf], np.nan)
    y = train[target].astype(float).replace([np.inf, -np.inf], np.nan)
    keep = x.notna().all(axis=1) & y.notna()
    x = x.loc[keep]
    y = y.loc[keep]
    if len(x) < max(10, len(features) + 2):
        raise ValueError(f"insufficient normal_cooling rows for {target}: {len(x)}")
    means = x.mean()
    stds = x.std().replace(0, 1.0)
    xz = (x - means) / stds
    design = np.column_stack([np.ones(len(xz)), xz.values])
    coef, *_ = np.linalg.lstsq(design, y.values, rcond=None)
    pred = design @ coef
    resid = y.values - pred
    return {
        "target": target,
        "features": features,
        "intercept": float(coef[0]),
        "coefficients": {f: float(c) for f, c in zip(features, coef[1:])},
        "feature_mean": means.to_dict(),
        "feature_std": stds.to_dict(),
        "residual_median": float(np.median(resid)),
        "residual_mad": float(np.median(np.abs(resid - np.median(resid))) * 1.4826),
    }


def predict_linear(df: pd.DataFrame, model: Dict[str, object]) -> pd.Series:
    features = list(model["features"])
    x = df[features].astype(float).replace([np.inf, -np.inf], np.nan)
    means = pd.Series(model["feature_mean"])
    stds = pd.Series(model["feature_std"]).replace(0, 1.0)
    xz = (x - means) / stds
    pred = float(model["intercept"])
    for feature, coef in model["coefficients"].items():
        pred = pred + xz[feature] * float(coef)
    return pred


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    dataset = Path(args.dataset)
    if not dataset.exists():
        write_status(out_dir, {"status": "not_run", "dataset": str(dataset), "reason": "dataset not found"})
        return 0

    df = pd.read_csv(dataset)
    load_cols = [c.strip() for c in args.load_cols.split(",") if c.strip()]
    target_cols = [c.strip() for c in args.target_cols.split(",") if c.strip()]
    forbidden_used = sorted(set(load_cols) & FORBIDDEN_PRIMARY_FEATURES)
    missing = [c for c in [args.condition_col] + load_cols + target_cols if c not in df.columns]
    if missing or forbidden_used:
        write_status(
            out_dir,
            {
                "status": "not_run",
                "dataset": str(dataset),
                "reason": "missing required columns or forbidden primary features requested",
                "missing_columns": missing,
                "forbidden_primary_features": forbidden_used,
            },
        )
        return 0

    train = df[df[args.condition_col] == args.train_condition].copy()
    if train.empty:
        write_status(out_dir, {"status": "not_run", "dataset": str(dataset), "reason": "no normal_cooling training rows"})
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    model_rows = []
    residual_df = df.copy()
    risk_parts = []
    for target in target_cols:
        model = fit_linear_expected(train, load_cols, target)
        pred = predict_linear(df, model)
        residual = pd.to_numeric(df[target], errors="coerce") - pred
        residual_df[f"{target}_expected"] = pred
        residual_df[f"{target}_residual"] = residual
        residual_df[f"{target}_residual_z"] = robust_z(
            residual,
            float(model["residual_median"]),
            float(model["residual_mad"]),
        )
        risk_parts.append(residual_df[f"{target}_residual_z"].abs())
        for feature, coef in model["coefficients"].items():
            model_rows.append({"target": target, "feature": feature, "coefficient": coef, "model": "linear_load_conditioned"})

    residual_df["composite_thermal_performance_risk_score"] = pd.concat(risk_parts, axis=1).mean(axis=1)
    summary_rows = []
    for cond, part in residual_df.groupby(args.condition_col):
        row = {"condition": cond, "rows": len(part)}
        for target in target_cols:
            row[f"{target}_residual_median"] = part[f"{target}_residual"].median()
            row[f"{target}_abs_residual_p95"] = part[f"{target}_residual"].abs().quantile(0.95)
        row["risk_score_p95"] = part["composite_thermal_performance_risk_score"].quantile(0.95)
        summary_rows.append(row)

    residual_df.to_csv(out_dir / "load_conditioned_residual_dataset.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(out_dir / "load_conditioned_residual_distribution_summary.csv", index=False)
    pd.DataFrame(model_rows).to_csv(out_dir / "load_conditioned_expected_behavior_coefficients.csv", index=False)
    write_status(
        out_dir,
        {
            "status": "completed",
            "dataset": str(dataset),
            "train_condition": args.train_condition,
            "feature_columns": load_cols,
            "target_columns": target_cols,
            "validation_note": "thresholds and residual scale are derived from training normal-cooling rows only",
        },
    )
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--condition-col", default="cooling_condition")
    p.add_argument("--train-condition", default="normal_cooling")
    p.add_argument("--load-cols", default="offered_rps,scheduled_request_count,inflight_count")
    p.add_argument("--target-cols", default="gpu_temp_c,sm_clock_mhz,server_total_latency_ms")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
