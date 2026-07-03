#!/usr/bin/env python3
"""Audit whether long normal-cooling baseline is ready for a matched pilot design."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def safe_max(series: pd.Series, default: float = 0.0) -> float:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    return float(vals.max()) if not vals.empty else default


def safe_sum(series: pd.Series) -> int:
    vals = pd.to_numeric(series, errors="coerce").fillna(0)
    return int(vals.sum()) if len(vals) else 0


def audit(args: argparse.Namespace) -> int:
    normal_root = Path(args.normal_long_analysis_dir)
    service_dir = normal_root / "service_state_normalized_validation_180s"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset = read_csv(normal_root / "openloop_load_conditioned_1s_dataset.csv")
    drift = read_csv(normal_root / "long_r07_r09_runstate_drift_summary.csv")
    episodes = read_csv(service_dir / "service_state_normalized_episode_summary.csv")
    manifest_gap = read_csv(normal_root / "manifest_gap_summary.csv")
    latency_quality = read_csv(normal_root / "latency_target_quality_summary.csv")

    eligible_rows = 0
    run_count = 0
    replicates: list[str] = []
    if not dataset.empty:
        eligible = dataset["eligible_for_formal_validation"].astype(str).str.lower().isin({"true", "1"})
        eligible_rows = int(eligible.sum())
        run_count = int(dataset["run_id"].nunique())
        replicates = sorted(str(x) for x in dataset["replicate_id"].dropna().unique())

    latency_episode_rows = pd.DataFrame()
    composite_episode_rows = pd.DataFrame()
    if not episodes.empty:
        latency_episode_rows = episodes[
            episodes["target"].astype(str).isin(["rolling_latency_p50", "rolling_latency_p95"])
        ]
        composite_episode_rows = episodes[episodes["target"].astype(str).str.contains("composite", na=False)]

    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "check": "normal_long_replicates",
            "status": "pass" if run_count >= args.min_normal_replicates else "fail",
            "observed": run_count,
            "required": args.min_normal_replicates,
            "reason": "need multiple independent long normal-cooling runs",
        }
    )
    checks.append(
        {
            "check": "formal_measurement_rows",
            "status": "pass" if eligible_rows >= args.min_formal_rows else "fail",
            "observed": eligible_rows,
            "required": args.min_formal_rows,
            "reason": "normal baseline must be long enough for held-out validation",
        }
    )
    checks.append(
        {
            "check": "manifest_validity",
            "status": "pass"
            if manifest_gap.empty or not manifest_gap["analysis_ineligible"].astype(str).str.lower().isin({"true", "1"}).any()
            else "fail",
            "observed": 0
            if manifest_gap.empty
            else int(manifest_gap["analysis_ineligible"].astype(str).str.lower().isin({"true", "1"}).sum()),
            "required": 0,
            "reason": "formal pilot requires complete manifest metadata",
        }
    )
    checks.append(
        {
            "check": "gpu_temp_internal_drift",
            "status": "pass"
            if not drift.empty and safe_max(drift["gpu_temp_first_to_last_delta_c"].abs()) <= args.max_gpu_temp_median_drift_c
            else "fail",
            "observed": None if drift.empty else safe_max(drift["gpu_temp_first_to_last_delta_c"].abs()),
            "required": f"<= {args.max_gpu_temp_median_drift_c}",
            "reason": "normal-cooling baseline should not contain large thermal drift",
        }
    )
    checks.append(
        {
            "check": "sm_clock_internal_drift",
            "status": "pass"
            if not drift.empty and safe_max(drift["sm_clock_first_to_last_delta_mhz"].abs()) <= args.max_sm_clock_median_drift_mhz
            else "fail",
            "observed": None if drift.empty else safe_max(drift["sm_clock_first_to_last_delta_mhz"].abs()),
            "required": f"<= {args.max_sm_clock_median_drift_mhz}",
            "reason": "normal-cooling baseline should not contain large clock-state drift",
        }
    )
    checks.append(
        {
            "check": "service_state_normalized_latency_episodes",
            "status": "pass" if safe_sum(latency_episode_rows.get("episode_count_after_calibration", pd.Series(dtype=float))) == 0 else "fail",
            "observed": safe_sum(latency_episode_rows.get("episode_count_after_calibration", pd.Series(dtype=float))),
            "required": 0,
            "reason": "latency residual baseline must be stable after run-local healthy calibration",
        }
    )

    decision = "ready_for_matched_pilot_design"
    if any(row["status"] == "fail" for row in checks):
        decision = "not_ready_collect_more_normal_or_fix_contract"
    if decision == "ready_for_matched_pilot_design":
        decision = "method_ready_but_live_cooling_executor_still_fail_closed"

    checks_df = pd.DataFrame(checks)
    checks_df.to_csv(out_dir / "matched_pilot_readiness_checks.csv", index=False)
    summary = {
        "decision": decision,
        "normal_long_analysis_dir": str(normal_root),
        "replicates": replicates,
        "run_count": run_count,
        "eligible_rows": eligible_rows,
        "latency_episode_count_after_180s_calibration": safe_sum(
            latency_episode_rows.get("episode_count_after_calibration", pd.Series(dtype=float))
        ),
        "composite_episode_count_after_180s_calibration": safe_sum(
            composite_episode_rows.get("episode_count_after_calibration", pd.Series(dtype=float))
        ),
        "cooling_constrained_live_executor_status": "not_implemented_fail_closed",
        "required_pilot_contract": {
            "warmup_duration_s": 180,
            "measurement_duration_s": 900,
            "post_observation_duration_s": 30,
            "run_local_healthy_calibration_window_s": 180,
            "primary_latency_scoring_after_calibration_only": True,
            "same_offered_rps_payload_model_endpoint": True,
        },
    }
    (out_dir / "analysis_manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = [
        "# Matched Cooling-Constrained Pilot Readiness Audit",
        "",
        f"- decision: `{decision}`",
        f"- normal long runs: `{run_count}`",
        f"- formal rows: `{eligible_rows}`",
        f"- latency episodes after 180s run-local calibration: `{summary['latency_episode_count_after_180s_calibration']}`",
        f"- composite episodes after 180s run-local calibration: `{summary['composite_episode_count_after_180s_calibration']}`",
        "",
        "## Checks",
        "",
        "| check | status | observed | required |",
        "|---|---|---:|---|",
    ]
    for row in checks:
        report.append(f"| {row['check']} | `{row['status']}` | {row['observed']} | {row['required']} |")
    report.extend(
        [
            "",
            "## Interpretation",
            "",
            "The long normal-cooling baseline supports designing a matched cooling-constrained pilot only if the pilot uses the same long warm-up, the same workload/payload/model settings, and a pre-registered 180s run-local healthy calibration window. The live cooling-constrained executor remains intentionally fail-closed.",
        ]
    )
    (out_dir / "MATCHED_PILOT_READINESS_AUDIT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if decision != "not_ready_collect_more_normal_or_fix_contract" else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--normal-long-analysis-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--min-normal-replicates", type=int, default=3)
    p.add_argument("--min-formal-rows", type=int, default=2700)
    p.add_argument("--max-gpu-temp-median-drift-c", type=float, default=2.0)
    p.add_argument("--max-sm-clock-median-drift-mhz", type=float, default=50.0)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(audit(parse_args()))
