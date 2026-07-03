#!/usr/bin/env python3
"""Post-process held-out normal residual validation with online service-state offset calibration."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


LATENCY_TARGET_PREFIXES = ("rolling_latency_", "completion_latency_")


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def q(series: pd.Series, quantile: float) -> float | None:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    return float(vals.quantile(quantile))


def rmse(series: pd.Series) -> float | None:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    return float((vals.pow(2).mean()) ** 0.5)


def target_from_exceed_col(col: str) -> str:
    return col.replace("_state_normalized_exceeds_threshold", "").replace("_exceeds_threshold", "")


def load_thresholds(validation_dir: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    path = validation_dir / "heldout_normal_thresholds.csv"
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (str(row.get("split")), str(row.get("fold")), str(row.get("target")))
            rows[key] = row
    return rows


def apply_state_normalization(
    scored: pd.DataFrame,
    thresholds: dict[tuple[str, str, str], dict[str, Any]],
    calibration_window_s: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = scored.copy()
    out["post_calibration_scoring"] = True
    offset_rows: list[dict[str, Any]] = []
    targets = sorted({c.replace("_residual", "") for c in scored.columns if c.endswith("_residual") and not c.endswith("_abs_residual")})
    for target in targets:
        is_latency = target.startswith(LATENCY_TARGET_PREFIXES)
        out[f"{target}_state_offset"] = 0.0
        out[f"{target}_state_normalized_residual"] = out[f"{target}_residual"]
        out[f"{target}_state_normalized_abs_residual"] = out[f"{target}_abs_residual"]
        out[f"{target}_state_normalized_exceeds_threshold"] = out[f"{target}_exceeds_threshold"]
        out[f"{target}_post_calibration_scoring"] = True
        if not is_latency:
            continue
        for (split, fold, run_id), idx in scored.groupby(["split", "fold", "run_id"], dropna=False).groups.items():
            part = scored.loc[idx].copy()
            elapsed = pd.to_numeric(part["elapsed_s"], errors="coerce")
            start = float(elapsed.min())
            calibration_mask = elapsed < start + calibration_window_s
            post_mask = elapsed >= start + calibration_window_s
            out.loc[idx, "post_calibration_scoring"] = post_mask
            resid = pd.to_numeric(part[f"{target}_residual"], errors="coerce")
            valid = bool_series(part.get(f"{target}_valid_for_scoring", pd.Series(True, index=part.index)))
            calib_resid = resid[calibration_mask & valid]
            offset = float(calib_resid.median()) if not calib_resid.dropna().empty else 0.0
            key = (str(split), str(fold), target)
            threshold = safe_float(thresholds.get(key, {}).get("threshold")) or float("inf")
            adj = resid - offset
            out.loc[idx, f"{target}_state_offset"] = offset
            out.loc[idx, f"{target}_state_normalized_residual"] = adj
            out.loc[idx, f"{target}_state_normalized_abs_residual"] = adj.abs()
            out.loc[idx, f"{target}_state_normalized_exceeds_threshold"] = (adj.abs() > threshold) & valid
            out.loc[idx, f"{target}_post_calibration_scoring"] = post_mask & valid
            offset_rows.append(
                {
                    "split": split,
                    "fold": fold,
                    "run_id": run_id,
                    "target": target,
                    "calibration_window_s": calibration_window_s,
                    "calibration_rows": int((calibration_mask & valid).sum()),
                    "scored_rows_after_calibration": int((post_mask & valid).sum()),
                    "state_offset": offset,
                    "threshold": threshold,
                    "offset_source": "heldout_run_initial_healthy_window_observed_at_or_before_scoring_period",
                }
            )

    # Recompute composite risk with normalized latency residuals and original non-latency residuals.
    out["composite_risk_score_state_normalized"] = 0.0
    out["composite_risk_exceeds_threshold_state_normalized"] = False
    for (split, fold), idx in out.groupby(["split", "fold"], dropna=False).groups.items():
        parts = []
        for target in targets:
            key = (str(split), str(fold), target)
            t = thresholds.get(key, {})
            center = safe_float(t.get("train_residual_center")) or 0.0
            scale = safe_float(t.get("train_residual_scale")) or 1.0
            resid_col = f"{target}_state_normalized_residual" if target.startswith(LATENCY_TARGET_PREFIXES) else f"{target}_residual"
            z = (pd.to_numeric(out.loc[idx, resid_col], errors="coerce") - center) / max(scale, 1e-9)
            parts.append(z.abs())
        if parts:
            risk = pd.concat(parts, axis=1).mean(axis=1)
            risk_threshold = safe_float(thresholds.get((str(split), str(fold), "composite_risk_score"), {}).get("threshold")) or float("inf")
            out.loc[idx, "composite_risk_score_state_normalized"] = risk
            out.loc[idx, "composite_risk_exceeds_threshold_state_normalized"] = risk > risk_threshold
    return out, pd.DataFrame(offset_rows)


def run_metrics(scored: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    targets = sorted({c.replace("_state_normalized_residual", "") for c in scored.columns if c.endswith("_state_normalized_residual")})
    for (split, fold, run_id), part in scored.groupby(["split", "fold", "run_id"], dropna=False):
        for target in targets:
            valid_col = f"{target}_post_calibration_scoring"
            valid = bool_series(part[valid_col]) if valid_col in part.columns else pd.Series(True, index=part.index)
            resid = pd.to_numeric(part[f"{target}_state_normalized_residual"], errors="coerce")
            exceeds = bool_series(part[f"{target}_state_normalized_exceeds_threshold"])
            rows.append(
                {
                    "split": split,
                    "fold": fold,
                    "run_id": run_id,
                    "target_offered_rps": safe_float(part["target_offered_rps"].median()),
                    "target": target,
                    "rows_after_calibration": int(valid.sum()),
                    "mae_after_calibration": safe_float(resid[valid].abs().mean()),
                    "rmse_after_calibration": rmse(resid[valid]),
                    "abs_residual_p50_after_calibration": q(resid[valid].abs(), 0.50),
                    "abs_residual_p95_after_calibration": q(resid[valid].abs(), 0.95),
                    "threshold_exceedance_rate_after_calibration": safe_float(exceeds[valid].mean()) if int(valid.sum()) else None,
                    "point_exceedance_count_after_calibration": int(exceeds[valid].sum()),
                }
            )
        valid = pd.Series(True, index=part.index)
        # Exclude the first calibration window if any latency target marks it.
        if "post_calibration_scoring" in part.columns:
            valid = bool_series(part["post_calibration_scoring"])
        comp_exceeds = bool_series(part["composite_risk_exceeds_threshold_state_normalized"])
        comp = pd.to_numeric(part["composite_risk_score_state_normalized"], errors="coerce")
        rows.append(
            {
                "split": split,
                "fold": fold,
                "run_id": run_id,
                "target_offered_rps": safe_float(part["target_offered_rps"].median()),
                "target": "composite_risk_score_state_normalized",
                "rows_after_calibration": int(valid.sum()),
                "abs_residual_p50_after_calibration": q(comp[valid], 0.50),
                "abs_residual_p95_after_calibration": q(comp[valid], 0.95),
                "threshold_exceedance_rate_after_calibration": safe_float(comp_exceeds[valid].mean()) if int(valid.sum()) else None,
                "point_exceedance_count_after_calibration": int(comp_exceeds[valid].sum()),
            }
        )
    return pd.DataFrame(rows)


def debounced_episode_summary(scored: pd.DataFrame, min_duration_s: int, refractory_s: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    exceed_cols = [c for c in scored.columns if c.endswith("_state_normalized_exceeds_threshold")]
    exceed_cols.append("composite_risk_exceeds_threshold_state_normalized")
    for (split, fold, run_id), part in scored.sort_values("elapsed_s").groupby(["split", "fold", "run_id"], dropna=False):
        elapsed = pd.to_numeric(part["elapsed_s"], errors="coerce")
        post_mask = bool_series(part["post_calibration_scoring"]) if "post_calibration_scoring" in part.columns else pd.Series(True, index=part.index)
        for col in exceed_cols:
            if col not in part.columns:
                continue
            flags = bool_series(part[col]) & post_mask
            episodes: list[tuple[float, float]] = []
            start = None
            prev = None
            for flag, ts in zip(flags.tolist(), elapsed.tolist()):
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
            merged: list[tuple[float, float]] = []
            for start_s, end_s in episodes:
                if end_s - start_s + 1 < min_duration_s:
                    continue
                if merged and start_s - merged[-1][1] <= refractory_s:
                    merged[-1] = (merged[-1][0], end_s)
                else:
                    merged.append((start_s, end_s))
            target = target_from_exceed_col(col)
            rows.append(
                {
                    "split": split,
                    "fold": fold,
                    "run_id": run_id,
                    "target_offered_rps": safe_float(part["target_offered_rps"].median()),
                    "target": target,
                    "scored_rows_after_calibration": int(post_mask.sum()),
                    "point_exceedance_count_after_calibration": int(flags.sum()),
                    "point_exceedance_rate_after_calibration": safe_float(flags[post_mask].mean()) if int(post_mask.sum()) else None,
                    "episode_count_after_calibration": len(merged),
                    "episode_total_duration_s_after_calibration": sum(int(end - start + 1) for start, end in merged),
                    "episode_max_duration_s_after_calibration": max((int(end - start + 1) for start, end in merged), default=0),
                    "episodes_after_calibration": ";".join(f"{int(start)}-{int(end)}" for start, end in merged),
                    "min_episode_duration_s": min_duration_s,
                    "refractory_s": refractory_s,
                }
            )
    return pd.DataFrame(rows)


def write_report(
    out_dir: Path,
    validation_dir: Path,
    scored: pd.DataFrame,
    offsets: pd.DataFrame,
    episodes: pd.DataFrame,
    calibration_window_s: int,
) -> None:
    comp = episodes[episodes["target"] == "composite_risk"]
    r02 = episodes[(episodes["run_id"].astype(str).str.contains("172916")) & (episodes["target"].astype(str).str.contains("rolling_latency_p50"))]
    report = [
        "# Service-State Normalized Held-Out Normal Validation",
        "",
        "## Scope",
        "",
        "This is an offline post-processing audit over held-out predictions. It does not rerun live experiments and does not use fan, phase, intervention, run ID, or future telemetry as model features.",
        "",
        "## Method",
        "",
        f"- calibration_window_s: `{calibration_window_s}`",
        "- For each held-out run, latency residual offset is estimated only from the initial calibration window of that same run.",
        "- The calibration window is excluded from formal episode scoring.",
        "- GPU temperature and SM clock residuals are not offset-normalized.",
        "- Composite risk is recomputed using normalized latency residuals plus original GPU-state residuals.",
        "",
        "## Summary",
        "",
        f"- input validation dir: `{validation_dir}`",
        f"- scored rows: `{len(scored)}`",
        f"- latency offset rows: `{len(offsets)}`",
        f"- composite total episodes after calibration: `{int(comp['episode_count_after_calibration'].sum()) if not comp.empty else 0}`",
        f"- r02 rolling_latency_p50 episodes after calibration: `{int(r02['episode_count_after_calibration'].sum()) if not r02.empty else 0}`",
        "",
        "## Interpretation",
        "",
        "If r02 latency episodes disappear after this online offset calibration, the earlier instability is best interpreted as normal service-state baseline shift rather than thermal-performance anomaly. This does not prove deployable generalization; it only shows that a run-local healthy calibration layer may be needed before latency residual is used as a primary warning signal.",
    ]
    (out_dir / "SERVICE_STATE_NORMALIZED_VALIDATION.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    validation_dir = Path(args.validation_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scored = pd.read_csv(validation_dir / "heldout_normal_scored_timeline.csv")
    thresholds = load_thresholds(validation_dir)
    normalized, offsets = apply_state_normalization(scored, thresholds, args.calibration_window_s)
    metrics = run_metrics(normalized)
    episodes = debounced_episode_summary(normalized, args.min_episode_duration_s, args.refractory_s)
    normalized.to_csv(out_dir / "service_state_normalized_scored_timeline.csv", index=False)
    offsets.to_csv(out_dir / "service_state_latency_offsets.csv", index=False)
    metrics.to_csv(out_dir / "service_state_normalized_run_metrics.csv", index=False)
    episodes.to_csv(out_dir / "service_state_normalized_episode_summary.csv", index=False)
    manifest = {
        "validation_dir": str(validation_dir),
        "calibration_window_s": args.calibration_window_s,
        "min_episode_duration_s": args.min_episode_duration_s,
        "refractory_s": args.refractory_s,
        "no_future_leakage_policy": "offset uses only held-out run initial window and excludes that window from formal scoring",
        "outputs": [
            "service_state_normalized_scored_timeline.csv",
            "service_state_latency_offsets.csv",
            "service_state_normalized_run_metrics.csv",
            "service_state_normalized_episode_summary.csv",
            "SERVICE_STATE_NORMALIZED_VALIDATION.md",
        ],
    }
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(out_dir, validation_dir, normalized, offsets, episodes, args.calibration_window_s)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--validation-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--calibration-window-s", type=int, default=60)
    p.add_argument("--min-episode-duration-s", type=int, default=3)
    p.add_argument("--refractory-s", type=int, default=5)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
