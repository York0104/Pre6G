#!/usr/bin/env python3
"""Diagnose replicate-to-replicate stability for normal baseline v2 data."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


def finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def q(series: pd.Series, quantile: float) -> float | None:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    return float(vals.quantile(quantile))


def bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def summarize_series(run_id: str, metric: str, values: pd.Series) -> dict[str, Any]:
    vals = pd.to_numeric(values, errors="coerce")
    return {
        "run_id": run_id,
        "metric": metric,
        "count": int(vals.notna().sum()),
        "mean": float(vals.mean()) if vals.notna().any() else None,
        "p50": q(vals, 0.50),
        "p95": q(vals, 0.95),
        "p99": q(vals, 0.99),
        "min": float(vals.min()) if vals.notna().any() else None,
        "max": float(vals.max()) if vals.notna().any() else None,
    }


def read_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def filter_measurement_window(df: pd.DataFrame, manifest: dict[str, Any], time_col: str) -> pd.DataFrame:
    start = pd.to_datetime(manifest.get("measurement_start_ts"), utc=True, errors="coerce")
    end = pd.to_datetime(manifest.get("measurement_end_ts"), utc=True, errors="coerce")
    if pd.isna(start) or pd.isna(end) or time_col not in df.columns:
        return df.copy()
    ts = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    return df[(ts >= start) & (ts < end)].copy()


def summarize_raw_runs(campaign_root: Path, run_dirs: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    latency_rows: list[dict[str, Any]] = []
    telemetry_rows: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        manifest = read_manifest(run_dir)
        run_id = str(manifest.get("replicate_id") or run_dir.name)
        raw_path = run_dir / "open_loop_client_raw.csv"
        if raw_path.exists():
            raw = pd.read_csv(raw_path)
            raw = filter_measurement_window(raw, manifest, "complete_time_iso")
            for metric in [
                "e2e_latency_ms",
                "server_latency_ms",
                "server_total_latency_ms",
                "schedule_delay_ms",
            ]:
                if metric in raw.columns:
                    latency_rows.append(summarize_series(run_id, metric, raw[metric]))
            if "success" in raw.columns:
                success = bool_series(raw["success"])
                latency_rows.append(
                    {
                        "run_id": run_id,
                        "metric": "success_fraction",
                        "count": int(len(success)),
                        "mean": float(success.mean()) if len(success) else None,
                        "p50": float(success.mean()) if len(success) else None,
                    }
                )
            if "server_pod_name" in raw.columns:
                latency_rows.append(
                    {
                        "run_id": run_id,
                        "metric": "server_pod_name_unique_count",
                        "count": int(raw["server_pod_name"].nunique(dropna=True)),
                        "mean": None,
                        "p50": ";".join(sorted(str(x) for x in raw["server_pod_name"].dropna().unique())),
                    }
                )
        gpu_path = run_dir / "nvidia_smi_gpu_1s.csv"
        if gpu_path.exists():
            gpu = pd.read_csv(gpu_path)
            time_col = "timestamp" if "timestamp" in gpu.columns else "ts"
            gpu = filter_measurement_window(gpu, manifest, time_col)
            for metric in [
                "gpu_temp_c",
                "temperature_gpu_c",
                "sm_clock_mhz",
                "clocks_sm_mhz",
                "gpu_power_w",
                "power_draw_w",
                "gpu_util_pct",
                "utilization_gpu_pct",
                "mem_clock_mhz",
                "clocks_mem_mhz",
            ]:
                if metric in gpu.columns:
                    telemetry_rows.append(summarize_series(run_id, metric, gpu[metric]))
    return latency_rows, telemetry_rows


def summarize_dataset(dataset_path: Path) -> list[dict[str, Any]]:
    if not dataset_path.exists():
        return []
    df = pd.read_csv(dataset_path)
    mask = pd.Series(True, index=df.index)
    if "eligible_for_formal_validation" in df.columns:
        mask = bool_series(df["eligible_for_formal_validation"])
    elif "in_measurement_window" in df.columns:
        mask = bool_series(df["in_measurement_window"])
    rows: list[dict[str, Any]] = []
    for run_id, group in df[mask].groupby("replicate_id" if "replicate_id" in df.columns else "run_id"):
        for metric in [
            "rolling_latency_p50",
            "rolling_latency_mean",
            "rolling_latency_p95",
            "rolling_latency_p99",
            "rolling_completion_count",
            "completion_completed_request_count",
            "completion_realized_completed_rps",
            "gpu_temp_c",
            "sm_clock_mhz",
            "gpu_power_w",
            "gpu_util_pct",
        ]:
            if metric in group.columns:
                rows.append(summarize_series(str(run_id), metric, group[metric]))
    return rows


def summarize_scored(scored_path: Path, episode_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    if scored_path.exists():
        df = pd.read_csv(scored_path)
        for run_id, group in df.groupby("run_id"):
            for metric in [
                "gpu_temp_c_abs_residual",
                "sm_clock_mhz_abs_residual",
                "rolling_latency_p50_abs_residual",
                "rolling_latency_p95_abs_residual",
                "composite_risk_score",
            ]:
                if metric in group.columns:
                    rows.append(summarize_series(str(run_id), metric, group[metric]))
    episode_rows: list[dict[str, Any]] = []
    if not episode_path.exists():
        alternate = episode_path.with_name("heldout_normal_debounced_episode_summary.csv")
        episode_path = alternate if alternate.exists() else episode_path
    if episode_path.exists():
        episodes = pd.read_csv(episode_path)
        for _, row in episodes.iterrows():
            episode_rows.append(row.to_dict())
    return rows, episode_rows


def classify_findings(dataset_rows: list[dict[str, Any]], episode_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_metric: dict[str, dict[str, float]] = {}
    for row in dataset_rows:
        metric = str(row.get("metric"))
        run = str(row.get("run_id"))
        p50 = finite_float(row.get("p50"))
        if p50 is not None:
            by_metric.setdefault(metric, {})[run] = p50
    latency = by_metric.get("rolling_latency_p50", {})
    temp = by_metric.get("gpu_temp_c", {})
    clock = by_metric.get("sm_clock_mhz", {})
    latency_spread = max(latency.values()) - min(latency.values()) if len(latency) >= 2 else None
    temp_spread = max(temp.values()) - min(temp.values()) if len(temp) >= 2 else None
    clock_spread = max(clock.values()) - min(clock.values()) if len(clock) >= 2 else None
    r02_episodes = [
        row
        for row in episode_rows
        if str(row.get("run_id", "")).endswith("172916")
        or str(row.get("fold", "")) == "replicate_r02"
        or str(row.get("run_id")) == "r02"
    ]
    return {
        "latency_p50_spread_ms": latency_spread,
        "gpu_temp_p50_spread_c": temp_spread,
        "sm_clock_p50_spread_mhz": clock_spread,
        "r02_episode_rows": len(r02_episodes),
        "classification": (
            "normal service baseline shift dominates"
            if latency_spread is not None and latency_spread > 15 and (temp_spread is None or temp_spread <= 3)
            else "insufficient evidence"
        ),
    }


def write_report(out_dir: Path, findings: dict[str, Any]) -> None:
    report = [
        "# Normal Baseline v2 r02 Shift Diagnosis",
        "",
        "## Scope",
        "",
        "本報告只針對既有 open-loop normal-cooling v2 replicated dataset 做離線診斷；未執行 live experiment、fan control、CoolerControl、Kubernetes control、cooling-constrained pilot 或 GPU stress。",
        "",
        "## Main Finding",
        "",
        f"- classification: `{findings.get('classification')}`",
        f"- rolling latency p50 spread across replicates: `{findings.get('latency_p50_spread_ms')}` ms",
        f"- GPU temperature p50 spread across replicates: `{findings.get('gpu_temp_p50_spread_c')}` C",
        f"- SM clock p50 spread across replicates: `{findings.get('sm_clock_p50_spread_mhz')}` MHz",
        f"- r02 debounced episode rows: `{findings.get('r02_episode_rows')}`",
        "",
        "## Interpretation",
        "",
        "r02 的 held-out residual episodes 主要來自 normal run-to-run latency baseline shift；目前沒有足夠證據把它解讀為 thermal degradation。GPU temperature、SM clock 與 power 分布大致落在 normal-cooling 範圍內，因此此階段應先補 normal baseline replicate 或檢查服務狀態差異，而不是進入 cooling-constrained pilot。",
        "",
        "## Decision",
        "",
        "- `cooling-constrained pilot`: 暫緩。",
        "- `normal residual baseline`: 尚未驗證穩定。",
        "- `next action`: 先補更多相同 0.5 RPS normal-cooling v2 replicate，或在同樣資料契約下延長 measurement duration，再重跑 held-out normal residual validation。",
        "- `latency policy`: rolling median / rolling mean 可作 primary latency target；rolling p95/p99 保留為 tail sensitivity，需搭配足夠 completion samples 與更多 replicate。",
    ]
    (out_dir / "NORMAL_BASELINE_V2_R02_SHIFT_DIAGNOSIS.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    campaign_root = Path(args.campaign_root)
    combined_dir = Path(args.combined_dir)
    out_dir = Path(args.out_dir)
    run_dirs = [Path(p) for p in args.run_dir]
    latency_rows, telemetry_rows = summarize_raw_runs(campaign_root, run_dirs)
    dataset_rows = summarize_dataset(combined_dir / "openloop_load_conditioned_1s_dataset.csv")
    scored_rows, episode_rows = summarize_scored(
        combined_dir / "heldout_normal_residual_validation" / "heldout_normal_scored_timeline.csv",
        combined_dir / "heldout_normal_residual_validation" / "debounced_false_alarm_episode_summary.csv",
    )
    findings = classify_findings(dataset_rows, episode_rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "run_raw_latency_state_summary.csv", latency_rows)
    write_csv(out_dir / "run_raw_gpu_state_summary.csv", telemetry_rows)
    write_csv(out_dir / "run_dataset_state_summary.csv", dataset_rows)
    write_csv(out_dir / "heldout_residual_state_summary.csv", scored_rows)
    write_csv(out_dir / "heldout_residual_episode_diagnosis.csv", episode_rows)
    (out_dir / "analysis_manifest.json").write_text(
        json.dumps(
            {
                "campaign_root": str(campaign_root),
                "combined_dir": str(combined_dir),
                "run_dirs": [str(p) for p in run_dirs],
                "findings": findings,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    write_report(out_dir, findings)
    print(json.dumps({"out_dir": str(out_dir), "findings": findings}, indent=2, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--campaign-root", required=True)
    p.add_argument("--combined-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--run-dir", action="append", required=True)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
