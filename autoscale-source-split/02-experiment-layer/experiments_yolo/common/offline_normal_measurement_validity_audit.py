#!/usr/bin/env python3
"""Measurement-validity and run-state audit for normal open-loop baselines."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

import numpy as np
import pandas as pd


GPU_UTIL_VM_COL = "vmagg.target_node_semantic.gpu_bound_features.gpu_compute.gpu_util_avg"


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def numeric_text(value: Any) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
    return float(match.group(0)) if match else None


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


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


def q(values: Iterable[float], quantile: float) -> float | None:
    vals = [float(v) for v in values if safe_float(v) is not None]
    if not vals:
        return None
    return float(np.quantile(vals, quantile))


def safe_corr(left: pd.Series, right: pd.Series) -> float | None:
    a = pd.to_numeric(left, errors="coerce")
    b = pd.to_numeric(right, errors="coerce")
    keep = a.notna() & b.notna()
    if int(keep.sum()) < 3:
        return None
    a = a[keep]
    b = b[keep]
    if float(a.std()) == 0.0 or float(b.std()) == 0.0:
        return None
    out = a.corr(b)
    return None if pd.isna(out) else float(out)


def list_run_dirs(root: Path) -> List[Path]:
    return [
        p
        for p in sorted(root.iterdir())
        if p.is_dir()
        and (p / "open_loop_completion_1s_summary.csv").exists()
        and (p / "nvidia_smi_gpu_1s.csv").exists()
    ]


def load_manifest(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / "run_manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def target_rps(run_dir: Path, manifest: Dict[str, Any]) -> float | None:
    value = manifest.get("offered_load_profile", {}).get("target_rps")
    out = safe_float(value)
    if out is not None:
        return out
    match = re.search(r"rps([0-9.]+)_", run_dir.name)
    return float(match.group(1)) if match else None


def manifest_gaps(manifest: Dict[str, Any]) -> tuple[Any, str]:
    profile = manifest.get("offered_load_profile", {}) if manifest else {}
    replicate = profile.get("replicate", manifest.get("replicate") if manifest else None)
    gaps = []
    if replicate is None:
        gaps.append("replicate_missing")
    if profile.get("target_rps") is None:
        gaps.append("offered_load_profile.target_rps_missing")
    if not manifest.get("created_at_utc"):
        gaps.append("created_at_utc_missing")
    if not manifest.get("warmup_s") and not manifest.get("warm_up_s"):
        gaps.append("warmup_metadata_missing")
    return replicate, ";".join(gaps)


def normalize_gpu_smi(path: Path) -> pd.DataFrame:
    raw = read_csv(path)
    if raw.empty:
        return pd.DataFrame()
    normalized = {str(c).strip(): c for c in raw.columns}
    out = pd.DataFrame({"elapsed_s": range(len(raw))})
    mapping = {
        "nvidia_gpu_util_pct": ["utilization.gpu [%]", "utilization.gpu"],
        "nvidia_power_w": ["power.draw [W]", "power.draw"],
        "nvidia_gpu_temp_c": ["temperature.gpu", "temperature.gpu [C]"],
        "nvidia_sm_clock_mhz": ["clocks.current.sm [MHz]", "clocks.sm [MHz]"],
    }
    for dest, choices in mapping.items():
        source = None
        for choice in choices:
            if choice in raw.columns:
                source = choice
                break
            if choice.strip() in normalized:
                source = normalized[choice.strip()]
                break
        if source:
            out[dest] = [numeric_text(v) for v in raw[source]]
    return out


def latency_sample_sufficiency(root: Path, min_samples: int) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for run_dir in list_run_dirs(root):
        manifest = load_manifest(run_dir)
        rps = target_rps(run_dir, manifest)
        replicate, gaps = manifest_gaps(manifest)
        arrival = read_csv(run_dir / "open_loop_arrival_1s_summary.csv")
        comp = read_csv(run_dir / "open_loop_completion_1s_summary.csv")
        base = arrival[["elapsed_s"]].copy() if not arrival.empty and "elapsed_s" in arrival else pd.DataFrame({"elapsed_s": range(60)})
        if not comp.empty:
            comp_cols = [
                c
                for c in (
                    "elapsed_s",
                    "completed_request_count",
                    "successful_completion_count",
                    "latency_p50",
                    "latency_p95",
                    "latency_p99",
                )
                if c in comp.columns
            ]
            base = base.merge(comp[comp_cols], on="elapsed_s", how="left")
        for _, row in base.iterrows():
            count = safe_float(row.get("completed_request_count")) or 0.0
            success = safe_float(row.get("successful_completion_count")) or 0.0
            rows.append(
                {
                    "run_id": run_dir.name,
                    "target_offered_rps": rps,
                    "manifest_replicate": replicate,
                    "manifest_gap": gaps,
                    "elapsed_s": int(row.get("elapsed_s", 0)),
                    "completion_count": count,
                    "successful_completion_count": success,
                    "latency_p50": safe_float(row.get("latency_p50")),
                    "latency_p95": safe_float(row.get("latency_p95")),
                    "latency_p99": safe_float(row.get("latency_p99")),
                    "latency_quantile_sample_sufficient": success >= min_samples,
                    "insufficiency_reason": "" if success >= min_samples else f"successful_completion_count<{min_samples}",
                }
            )
    return pd.DataFrame(rows)


def measurement_mask(dataset: pd.DataFrame, min_latency_samples: int, warmup_s: int) -> pd.DataFrame:
    rows = []
    for _, row in dataset.iterrows():
        completion_count = safe_float(row.get("completion_completed_request_count")) or 0.0
        elapsed = safe_float(row.get("elapsed_s")) or 0.0
        warmup_ok = elapsed >= warmup_s
        latency_ok = completion_count >= min_latency_samples
        telemetry_ok = all(
            safe_float(row.get(col)) is not None
            for col in ("gpu_temp_c", "sm_clock_mhz", "gpu_power_w", "gpu_util_pct")
        )
        rows.append(
            {
                "run_id": row.get("run_id"),
                "target_offered_rps": row.get("target_offered_rps"),
                "elapsed_s": elapsed,
                "completion_count": completion_count,
                "eligible_for_thermal_clock_validation": bool(warmup_ok and telemetry_ok),
                "eligible_for_latency_tail_validation": bool(warmup_ok and telemetry_ok and latency_ok),
                "warmup_masked": not warmup_ok,
                "latency_sample_insufficient": not latency_ok,
                "telemetry_missing": not telemetry_ok,
                "warmup_s": warmup_s,
                "min_latency_samples": min_latency_samples,
            }
        )
    return pd.DataFrame(rows)


def warmup_runstate_audit(dataset: pd.DataFrame, scored: pd.DataFrame | None) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    residual_cols = []
    if scored is not None and not scored.empty:
        residual_cols = [c for c in scored.columns if c.endswith("_abs_residual")]
    for run_id, part in dataset.groupby("run_id"):
        n = len(part)
        if n == 0:
            continue
        bins = [
            ("early", part[part["elapsed_s"] < n / 3]),
            ("middle", part[(part["elapsed_s"] >= n / 3) & (part["elapsed_s"] < 2 * n / 3)]),
            ("late", part[part["elapsed_s"] >= 2 * n / 3]),
        ]
        scored_part = scored[scored["run_id"] == run_id] if scored is not None and "run_id" in scored else pd.DataFrame()
        for segment, seg in bins:
            scored_seg = pd.DataFrame()
            if not scored_part.empty:
                scored_seg = scored_part[scored_part["elapsed_s"].isin(seg["elapsed_s"])]
            row: Dict[str, Any] = {
                "run_id": run_id,
                "target_offered_rps": float(part["target_offered_rps"].median()),
                "segment": segment,
                "rows": len(seg),
                "gpu_temp_c_median": q(pd.to_numeric(seg.get("gpu_temp_c"), errors="coerce").dropna(), 0.5),
                "sm_clock_mhz_median": q(pd.to_numeric(seg.get("sm_clock_mhz"), errors="coerce").dropna(), 0.5),
                "gpu_power_w_median": q(pd.to_numeric(seg.get("gpu_power_w"), errors="coerce").dropna(), 0.5),
                "gpu_util_pct_median": q(pd.to_numeric(seg.get("gpu_util_pct"), errors="coerce").dropna(), 0.5),
                "latency_p95_median": q(pd.to_numeric(seg.get("rolling_latency_p95", seg.get("completion_latency_p95")), errors="coerce").dropna(), 0.5),
            }
            for col in residual_cols:
                row[f"{col}_median"] = q(pd.to_numeric(scored_seg.get(col), errors="coerce").dropna(), 0.5) if not scored_seg.empty else None
            rows.append(row)
    return pd.DataFrame(rows)


def residual_timing_audit(scored: pd.DataFrame, warmup_s: int) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    exceed_cols = [c for c in scored.columns if c.endswith("_exceeds_threshold")]
    for (split, fold, run_id), part in scored.groupby(["split", "fold", "run_id"], dropna=False):
        for col in exceed_cols:
            target = col.replace("_exceeds_threshold", "")
            flagged = part[part[col].astype(bool)]
            early = flagged[flagged["elapsed_s"] < warmup_s]
            rows.append(
                {
                    "split": split,
                    "fold": fold,
                    "run_id": run_id,
                    "target": target,
                    "target_offered_rps": float(part["target_offered_rps"].median()),
                    "rows": len(part),
                    "exceedance_count": len(flagged),
                    "early_exceedance_count": len(early),
                    "early_exceedance_fraction": len(early) / len(flagged) if len(flagged) else 0.0,
                    "first_exceedance_elapsed_s": q(flagged["elapsed_s"], 0.0) if len(flagged) else None,
                    "warmup_s": warmup_s,
                }
            )
    return pd.DataFrame(rows)


def parse_gpu_util_promql(sidecar_path: Path) -> Dict[str, Any]:
    if not sidecar_path.exists():
        return {"sidecar_exists": False}
    metrics = []
    promql_examples = []
    windows = []
    query_indices = set()
    sample_ages = []
    with sidecar_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            for sample in row.get("samples") or []:
                promql = str(sample.get("promql") or "")
                if "GPU_UTIL" not in promql and "gpu_util" not in promql.lower():
                    continue
                if promql and promql not in promql_examples and len(promql_examples) < 3:
                    promql_examples.append(promql)
                query_indices.add(sample.get("query_index"))
                metric = re.match(r"\s*([A-Za-z_:][A-Za-z0-9_:]*)", promql)
                metrics.append(metric.group(1) if metric else "")
                windows.extend(re.findall(r"\[([0-9]+[smhd])\]", promql))
                age = safe_float(sample.get("sample_age_max_s"))
                if age is not None:
                    sample_ages.append(age)
    return {
        "sidecar_exists": True,
        "gpu_util_query_indices": ",".join(str(x) for x in sorted(query_indices)),
        "metric_names": ",".join(sorted(set(metrics))),
        "promql_examples": " | ".join(promql_examples),
        "sample_age_max_s": max(sample_ages) if sample_ages else None,
        "labels_available_in_sidecar": False,
        "unit_available_in_sidecar": False,
        "aggregation_window_available_in_sidecar": bool(windows),
        "aggregation_windows_inferred_from_promql": ",".join(sorted(set(windows))),
        "semantic_capture_gap": "labels_missing;unit_missing" + ("" if windows else ";aggregation_window_missing"),
    }


def vm_gpu_util_audit(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    audit_rows = []
    lag_rows = []
    for run_dir in list_run_dirs(root):
        manifest = load_manifest(run_dir)
        rps = target_rps(run_dir, manifest)
        smi = normalize_gpu_smi(run_dir / "nvidia_smi_gpu_1s.csv")
        vm = read_csv(run_dir / "vm_aggregator_timeseries.csv")
        if not vm.empty:
            vm = pd.DataFrame(
                {
                    "elapsed_s": range(len(vm)),
                    "vm_gpu_util_avg": pd.to_numeric(vm.get(GPU_UTIL_VM_COL), errors="coerce"),
                }
            )
        merged = smi.merge(vm, on="elapsed_s", how="inner") if not smi.empty and not vm.empty else pd.DataFrame()
        promql = parse_gpu_util_promql(run_dir / "vm_aggregator_timeseries.vm_query_samples.jsonl")
        if merged.empty:
            corr = mae = med_abs = None
        else:
            corr = safe_corr(merged["nvidia_gpu_util_pct"], merged["vm_gpu_util_avg"])
            diff = (merged["nvidia_gpu_util_pct"] - merged["vm_gpu_util_avg"]).abs()
            mae = float(diff.mean())
            med_abs = float(diff.median())
            for lag in range(-30, 31):
                shifted = merged["vm_gpu_util_avg"].shift(lag)
                corr_lag = safe_corr(merged["nvidia_gpu_util_pct"], shifted)
                lag_rows.append(
                    {
                        "run_id": run_dir.name,
                        "target_offered_rps": rps,
                        "lag_s": lag,
                        "corr": corr_lag,
                        "samples": int((merged["nvidia_gpu_util_pct"].notna() & shifted.notna()).sum()),
                    }
                )
        decision = "insufficient evidence"
        if corr is not None and not pd.isna(corr):
            if corr >= 0.7 and (med_abs or 999) <= 10:
                decision = "same semantic metric"
            elif abs(corr) < 0.3 or (med_abs or 0) > 20:
                decision = "mismatched semantic metric"
        audit_rows.append(
            {
                "run_id": run_dir.name,
                "target_offered_rps": rps,
                "same_gpu_identity_available": bool(manifest.get("node_gpu_identity", {}).get("gpu_uuid")),
                "nvidia_rows": len(smi),
                "vm_rows": len(vm),
                "overlap_rows": len(merged),
                "zero_lag_corr": None if corr is None or pd.isna(corr) else float(corr),
                "mae": mae,
                "median_absolute_difference": med_abs,
                "semantic_decision": decision,
                **promql,
            }
        )
    return pd.DataFrame(audit_rows), pd.DataFrame(lag_rows)


def debounced_episodes(scored: pd.DataFrame, mask: pd.DataFrame, min_duration_s: int, refractory_s: int) -> pd.DataFrame:
    mask_key = mask[["run_id", "elapsed_s", "eligible_for_thermal_clock_validation", "eligible_for_latency_tail_validation"]]
    work = scored.merge(mask_key, on=["run_id", "elapsed_s"], how="left")
    rows: List[Dict[str, Any]] = []
    target_cols = [c for c in work.columns if c.endswith("_exceeds_threshold")]
    for (split, fold, run_id), part in work.sort_values("elapsed_s").groupby(["split", "fold", "run_id"], dropna=False):
        for col in target_cols:
            target = col.replace("_exceeds_threshold", "")
            eligibility_col = "eligible_for_latency_tail_validation" if "latency" in target else "eligible_for_thermal_clock_validation"
            eligible = part[part[eligibility_col].fillna(False).astype(bool)]
            flags = eligible[col].fillna(False).astype(bool).tolist()
            elapsed = eligible["elapsed_s"].tolist()
            episodes = []
            start = None
            prev = None
            for flag, ts in zip(flags, elapsed):
                if flag and start is None:
                    start = ts
                    prev = ts
                elif flag:
                    prev = ts
                elif start is not None:
                    episodes.append((start, prev))
                    start = None
                    prev = None
            if start is not None:
                episodes.append((start, prev))
            filtered = []
            last_end = -10**9
            for start_s, end_s in episodes:
                duration = int(end_s - start_s + 1)
                if duration < min_duration_s:
                    continue
                if start_s - last_end <= refractory_s and filtered:
                    old_start, _ = filtered[-1]
                    filtered[-1] = (old_start, end_s)
                else:
                    filtered.append((start_s, end_s))
                last_end = filtered[-1][1]
            eligible_seconds = len(eligible)
            rows.append(
                {
                    "split": split,
                    "fold": fold,
                    "run_id": run_id,
                    "target_offered_rps": float(part["target_offered_rps"].median()),
                    "target": target,
                    "eligible_seconds": eligible_seconds,
                    "point_exceedance_count": int(eligible[col].fillna(False).astype(bool).sum()) if not eligible.empty else 0,
                    "point_exceedance_rate": float(eligible[col].fillna(False).astype(bool).mean()) if not eligible.empty else 0.0,
                    "episode_count": len(filtered),
                    "episode_total_duration_s": sum(int(e - s + 1) for s, e in filtered),
                    "episode_max_duration_s": max((int(e - s + 1) for s, e in filtered), default=0),
                    "episodes": ";".join(f"{int(s)}-{int(e)}" for s, e in filtered),
                    "min_episode_duration_s": min_duration_s,
                    "refractory_s": refractory_s,
                    "note": "FA/hour intentionally omitted for 60-second runs; use episode count/rate instead",
                }
            )
    return pd.DataFrame(rows)


def write_report(
    out_dir: Path,
    latency_df: pd.DataFrame,
    warmup_df: pd.DataFrame,
    timing_df: pd.DataFrame,
    vm_audit: pd.DataFrame,
    episodes: pd.DataFrame,
    min_latency_samples: int,
    warmup_s: int,
) -> None:
    low_sparse = False
    if not latency_df.empty:
        suff = latency_df.groupby("target_offered_rps")["latency_quantile_sample_sufficient"].mean()
        low_sparse = bool((suff < 0.5).any())
    warmup_effect = bool((timing_df.get("early_exceedance_fraction", pd.Series(dtype=float)) > 0.5).any())
    telemetry_mismatch = bool((vm_audit.get("semantic_decision", pd.Series(dtype=str)) == "mismatched semantic metric").any())
    true_instability = bool((episodes.get("episode_count", pd.Series(dtype=float)) > 0).any())
    categories = []
    if low_sparse:
        categories.append("low-RPS measurement sparsity")
    if warmup_effect:
        categories.append("warm-up / run-state effect")
    if telemetry_mismatch:
        categories.append("telemetry semantic mismatch")
    if true_instability:
        categories.append("true normal baseline instability")
    if not categories:
        categories.append("insufficient evidence")

    latency_by_rps = latency_df.groupby("target_offered_rps").agg(
        bins=("elapsed_s", "count"),
        sufficient_fraction=("latency_quantile_sample_sufficient", "mean"),
        completion_count_median=("completion_count", "median"),
    )
    manifest_gap_summary = (
        latency_df[["run_id", "manifest_gap"]]
        .drop_duplicates()
        .assign(manifest_gap=lambda d: d["manifest_gap"].replace("", "none"))
        .groupby("manifest_gap")
        .size()
        .reset_index(name="runs")
    )
    vm_summary = vm_audit.groupby("semantic_decision").size().reset_index(name="runs") if not vm_audit.empty else pd.DataFrame()
    ep_summary = episodes.groupby(["target", "target_offered_rps"]).agg(
        runs=("run_id", "nunique"),
        episode_count=("episode_count", "sum"),
        median_point_exceedance_rate=("point_exceedance_rate", "median"),
    ).reset_index() if not episodes.empty else pd.DataFrame()

    lines = [
        "# Normal baseline measurement-validity audit",
        "",
        f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`",
        f"- min latency samples per bin: `{min_latency_samples}`",
        f"- warm-up mask: first `{warmup_s}` seconds excluded from formal validation",
        f"- conclusion categories: `{'; '.join(categories)}`",
        "",
        "## Latency Sample Sufficiency",
        "",
        "| offered_rps | bins | sufficient_fraction | completion_count_median |",
        "|---:|---:|---:|---:|",
    ]
    for rps, row in latency_by_rps.iterrows():
        lines.append(f"| {rps} | {int(row['bins'])} | {row['sufficient_fraction']:.3f} | {row['completion_count_median']:.3f} |")
    lines.extend(["", "## Replicate Identity / Manifest Gap", "", "| manifest_gap | runs |", "|---|---:|"])
    for _, row in manifest_gap_summary.iterrows():
        lines.append(f"| `{row['manifest_gap']}` | {row['runs']} |")
    lines.extend(["", "## VM GPU Util Semantic Audit", "", "| decision | runs |", "|---|---:|"])
    for _, row in vm_summary.iterrows():
        lines.append(f"| `{row['semantic_decision']}` | {row['runs']} |")
    lines.extend(["", "## Debounced Episodes", "", "| target | offered_rps | runs | episodes | median point exceedance |", "|---|---:|---:|---:|---:|"])
    for _, row in ep_summary.iterrows():
        lines.append(
            f"| `{row['target']}` | {row['target_offered_rps']} | {row['runs']} | {row['episode_count']} | {row['median_point_exceedance_rate']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- 只有 1 個 completion 的 1-second bin 不應被解讀為穩定 tail-latency evidence。",
            "- warm-up / telemetry stabilization mask 用於 measurement eligibility，不是 primary model feature。",
            "- VM `gpu_util_avg` 在 semantic 判定完成前不得作為 primary feature。",
            "- 60-second runs 不應只用 raw point count 外推長期 FA/hour；episode count 與 duration 是較合適的短 run sensitivity metric。",
        ]
    )
    text = "\n".join(lines) + "\n"
    (out_dir / "NORMAL_BASELINE_MEASUREMENT_VALIDITY_AUDIT.md").write_text(text, encoding="utf-8")
    (out_dir / "final_report_zh.md").write_text(text, encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    root = Path(args.input_root)
    out_dir = Path(args.out_dir)
    dataset = read_csv(Path(args.dataset))
    scored = read_csv(Path(args.scored_timeline))
    out_dir.mkdir(parents=True, exist_ok=True)

    latency = latency_sample_sufficiency(root, args.min_latency_samples)
    latency.to_csv(out_dir / "latency_sample_sufficiency_audit.csv", index=False)
    mask = measurement_mask(dataset, args.min_latency_samples, args.warmup_s)
    mask.to_csv(out_dir / "measurement_eligibility_mask.csv", index=False)
    warmup = warmup_runstate_audit(dataset, scored)
    warmup.to_csv(out_dir / "warmup_runstate_audit.csv", index=False)
    timing = residual_timing_audit(scored, args.warmup_s)
    timing.to_csv(out_dir / "residual_exceedance_timing_audit.csv", index=False)
    vm_audit, lag_scan = vm_gpu_util_audit(root)
    vm_audit.to_csv(out_dir / "vm_gpu_util_semantic_audit.csv", index=False)
    lag_scan.to_csv(out_dir / "vm_gpu_util_lag_scan.csv", index=False)
    episodes = debounced_episodes(scored, mask, args.min_episode_duration_s, args.refractory_s)
    episodes.to_csv(out_dir / "debounced_false_alarm_episode_summary.csv", index=False)

    manifest = {
        "input_root": str(root),
        "dataset": str(args.dataset),
        "scored_timeline": str(args.scored_timeline),
        "min_latency_samples": args.min_latency_samples,
        "warmup_s": args.warmup_s,
        "min_episode_duration_s": args.min_episode_duration_s,
        "refractory_s": args.refractory_s,
        "raw_dataset_modified": False,
        "notes": "offline audit only; no live experiment or control action",
    }
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(out_dir, latency, warmup, timing, vm_audit, episodes, args.min_latency_samples, args.warmup_s)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--scored-timeline", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--min-latency-samples", type=int, default=5)
    p.add_argument("--warmup-s", type=int, default=10)
    p.add_argument("--min-episode-duration-s", type=int, default=3)
    p.add_argument("--refractory-s", type=int, default=5)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
