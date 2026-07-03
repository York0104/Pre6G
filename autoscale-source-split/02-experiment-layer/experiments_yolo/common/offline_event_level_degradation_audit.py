#!/usr/bin/env python3
"""Event-level onset-only early-warning audit.

This is intentionally event-centric: already degraded intervals and recovery
transitions are excluded from the primary warning denominator.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

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
    "future_latency",
    "future_degraded",
}


def status(out_dir: Path, payload: Dict[str, object]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    (out_dir / "event_level_audit_status.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    report = [
        "# Event-level degradation early-warning audit",
        "",
        f"- status: `{payload.get('status')}`",
        f"- reason: {payload.get('reason', '')}",
        "",
        "Primary evaluation is onset-only. Row-level PR-AUC alone is not considered sufficient.",
    ]
    (out_dir / "event_level_audit_report_zh.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def parse_bool_value(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return False
    if isinstance(value, (int, np.integer)):
        return value != 0
    if isinstance(value, float):
        return value != 0.0
    text = str(value).strip().lower()
    if text in ("true", "t", "yes", "y", "1", "on", "warning", "degraded"):
        return True
    if text in ("false", "f", "no", "n", "0", "off", "", "none", "nan", "healthy", "normal"):
        return False
    raise ValueError(f"cannot parse boolean value: {value!r}")


def parse_boolean_series(series: pd.Series, column_name: str) -> pd.Series:
    try:
        return series.map(parse_bool_value).astype(bool)
    except ValueError as exc:
        raise ValueError(f"{column_name}: {exc}") from exc


def debounce_alerts(df: pd.DataFrame, run_col: str, time_col: str, warning_col: str, refractory_s: float) -> pd.DataFrame:
    alerts = []
    for run_id, part in df[df[warning_col]].sort_values([run_col, time_col]).groupby(run_col):
        last_alert_t: Optional[float] = None
        for idx, row in part.iterrows():
            t = float(row[time_col])
            if last_alert_t is None or t - last_alert_t >= refractory_s:
                alerts.append({"alert_index": idx, run_col: run_id, "alert_time_s": t})
                last_alert_t = t
    return pd.DataFrame(alerts, columns=["alert_index", run_col, "alert_time_s"])


def identify_onsets(
    df: pd.DataFrame,
    run_col: str,
    time_col: str,
    degraded_col: str,
    min_healthy_runin_s: float,
) -> pd.DataFrame:
    rows = []
    for run_id, part in df.sort_values([run_col, time_col]).groupby(run_col):
        first = True
        prev = False
        healthy_since: Optional[float] = None
        for _, row in part.iterrows():
            t = float(row[time_col])
            cur = parse_bool_value(row[degraded_col])
            if first:
                first = False
                if not cur:
                    healthy_since = t
                prev = cur
                continue
            if not cur and prev:
                healthy_since = t
            if cur and not prev:
                runin = t - healthy_since if healthy_since is not None else 0.0
                if runin >= min_healthy_runin_s:
                    rows.append({run_col: run_id, "onset_time_s": t, "healthy_runin_s": runin})
            prev = cur
    return pd.DataFrame(rows)


def time_span_hours(df: pd.DataFrame, run_col: str, time_col: str) -> float:
    total_s = 0.0
    for _, part in df.groupby(run_col):
        times = pd.to_numeric(part[time_col], errors="coerce").dropna().sort_values()
        if len(times) >= 2:
            total_s += max(0.0, float(times.iloc[-1] - times.iloc[0]))
    return max(total_s / 3600.0, 1e-9)


def event_metrics(
    df: pd.DataFrame,
    onsets: pd.DataFrame,
    alerts: pd.DataFrame,
    run_col: str,
    time_col: str,
    min_lead_s: float,
    max_lead_s: float,
    healthy_mask: pd.Series,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    events = []
    healthy = df[healthy_mask].copy()
    available_alerts = alerts.copy()
    used_alert_indices = set()
    for _, onset in onsets.iterrows():
        run_id = onset[run_col]
        onset_t = float(onset["onset_time_s"])
        cand = available_alerts[
            (available_alerts[run_col] == run_id)
            & (available_alerts["alert_time_s"] <= onset_t - min_lead_s)
            & (available_alerts["alert_time_s"] >= onset_t - max_lead_s)
            & (~available_alerts["alert_index"].isin(used_alert_indices))
        ]
        if cand.empty:
            events.append({run_col: run_id, "onset_time_s": onset_t, "detected": False, "lead_time_s": np.nan, "warnings": 0})
            continue
        chosen = cand.sort_values("alert_time_s").iloc[0]
        first_t = float(chosen["alert_time_s"])
        used_alert_indices.add(int(chosen["alert_index"]))
        events.append(
            {
                run_col: run_id,
                "onset_time_s": onset_t,
                "detected": True,
                "lead_time_s": onset_t - first_t,
                "warnings": 1,
                "matched_alert_index": int(chosen["alert_index"]),
            }
        )

    event_df = pd.DataFrame(events)
    healthy_alerts = alerts[alerts["alert_index"].isin(healthy.index)]
    false_alerts = healthy_alerts[~healthy_alerts["alert_index"].isin(used_alert_indices)]
    healthy_hours = time_span_hours(healthy, run_col, time_col)
    metrics = {
        "events": float(len(event_df)),
        "event_recall": float(event_df["detected"].mean()) if len(event_df) else 0.0,
        "missed_event_rate": float((~event_df["detected"]).mean()) if len(event_df) else 0.0,
        "false_alarms_per_healthy_hour": float(len(false_alerts) / healthy_hours),
        "warnings_per_event": float(event_df["warnings"].mean()) if len(event_df) else 0.0,
        "warning_precision": float(len(used_alert_indices) / max(len(healthy_alerts), 1)),
        "median_warning_lead_time_s": float(event_df["lead_time_s"].median(skipna=True)) if len(event_df) else np.nan,
        "iqr_warning_lead_time_s": float(event_df["lead_time_s"].quantile(0.75) - event_df["lead_time_s"].quantile(0.25)) if len(event_df) else np.nan,
        "healthy_duration_hours": float(healthy_hours),
        "debounced_alerts": float(len(alerts)),
    }
    return event_df, metrics


def read_feature_artifact(paths: Iterable[str]) -> Tuple[List[str], List[str]]:
    features: List[str] = []
    loaded: List[str] = []
    for raw in paths:
        if not raw:
            continue
        path = Path(raw)
        if not path.exists():
            continue
        loaded.append(str(path))
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                values = payload.get("features") or payload.get("feature_columns") or payload.get("primary_features") or []
            else:
                values = payload
            features.extend([str(v) for v in values])
        else:
            text = path.read_text(encoding="utf-8")
            features.extend([line.strip() for line in text.splitlines() if line.strip()])
    return features, loaded


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    data_path = Path(args.dataset)
    if not data_path.exists():
        status(out_dir, {"status": "not_run", "reason": "dataset not found", "dataset": str(data_path)})
        return 0
    df = pd.read_csv(data_path)
    required = [args.run_col, args.time_col, args.degraded_col, args.warning_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        status(out_dir, {"status": "not_run", "reason": "missing required columns", "missing_columns": missing})
        return 0
    artifact_features, loaded_artifacts = read_feature_artifact([args.model_manifest, args.feature_list_artifact])
    forbidden = sorted(set(artifact_features) & FORBIDDEN_PRIMARY_FEATURES)
    if forbidden:
        status(out_dir, {"status": "not_run", "reason": "forbidden feature found in model artifact", "forbidden_features": forbidden})
        return 0

    df = df.sort_values([args.run_col, args.time_col]).reset_index(drop=True)
    try:
        df[args.degraded_col] = parse_boolean_series(df[args.degraded_col], args.degraded_col)
        df[args.warning_col] = parse_boolean_series(df[args.warning_col], args.warning_col)
    except ValueError as exc:
        status(out_dir, {"status": "not_run", "reason": str(exc)})
        return 0
    onsets = identify_onsets(df, args.run_col, args.time_col, args.degraded_col, args.min_healthy_runin_s)
    if onsets.empty:
        status(out_dir, {"status": "not_run", "reason": "no degradation onsets found"})
        return 0

    already_degraded = df[args.degraded_col]
    recovery_exclude = pd.Series(False, index=df.index)
    for _, onset in onsets.iterrows():
        same_run = df[args.run_col] == onset[args.run_col]
        after = (df[args.time_col] >= onset["onset_time_s"]) & (df[args.time_col] <= onset["onset_time_s"] + args.exclude_after_onset_s)
        recovery_exclude |= same_run & after
    healthy_mask = (~already_degraded) & (~recovery_exclude)
    alerts = debounce_alerts(df[healthy_mask], args.run_col, args.time_col, args.warning_col, args.refractory_s)
    event_df, metrics = event_metrics(df, onsets, alerts, args.run_col, args.time_col, args.min_lead_s, args.max_lead_s, healthy_mask)

    out_dir.mkdir(parents=True, exist_ok=True)
    onsets.to_csv(out_dir / "degradation_onsets.csv", index=False)
    alerts.to_csv(out_dir / "debounced_alerts.csv", index=False)
    event_df.to_csv(out_dir / "event_level_warning_outcomes.csv", index=False)
    pd.DataFrame([metrics]).to_csv(out_dir / "event_level_warning_metrics.csv", index=False)
    status(
        out_dir,
        {
            "status": "completed",
            "dataset": str(data_path),
            "min_lead_s": args.min_lead_s,
            "max_lead_s": args.max_lead_s,
            "min_healthy_runin_s": args.min_healthy_runin_s,
            "refractory_s": args.refractory_s,
            "feature_leakage_audit_status": "artifact_checked" if loaded_artifacts else "not_performed_no_model_artifact",
            "feature_artifacts_loaded": loaded_artifacts,
            "metrics": metrics,
            "negative_controls_required": ["time-only", "offered-load-only", "thermal-only", "thermal-plus-service-history"],
        },
    )
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--run-col", default="run_id")
    p.add_argument("--time-col", default="time_s")
    p.add_argument("--degraded-col", default="service_degraded")
    p.add_argument("--warning-col", default="warning")
    p.add_argument("--model-manifest", default="")
    p.add_argument("--feature-list-artifact", default="")
    p.add_argument("--min-lead-s", type=float, default=0.0)
    p.add_argument("--max-lead-s", type=float, default=30.0)
    p.add_argument("--min-healthy-runin-s", type=float, default=1.0)
    p.add_argument("--refractory-s", type=float, default=30.0)
    p.add_argument("--exclude-after-onset-s", type=float, default=60.0)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
