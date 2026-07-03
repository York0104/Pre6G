#!/usr/bin/env python3
"""Check VM-derived telemetry feature candidates on normal-cooling calibration runs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


EXCLUDE_PREFIXES = (
    "vmagg._debug.",
    "vmagg.meta.",
)

EXCLUDE_SUBSTRINGS = (
    ".source",
    ".status",
    ".mode",
)


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def f(row: Dict[str, str], key: str, default: float = 0.0) -> float:
    raw = str(row.get(key, "") or "").strip()
    if not raw:
        return default
    match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
    return float(match.group(0)) if match else default


def pearson(xs: List[float], ys: List[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys) if math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 3:
        return None
    x_vals = [p[0] for p in pairs]
    y_vals = [p[1] for p in pairs]
    mx = sum(x_vals) / len(x_vals)
    my = sum(y_vals) / len(y_vals)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    denx = math.sqrt(sum((x - mx) ** 2 for x in x_vals))
    deny = math.sqrt(sum((y - my) ** 2 for y in y_vals))
    if denx == 0 or deny == 0:
        return None
    return num / (denx * deny)


def percentile(values: List[float], q: float) -> float | None:
    vals = sorted(v for v in values if math.isfinite(v))
    if not vals:
        return None
    idx = (len(vals) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(vals) - 1)
    frac = idx - lo
    return vals[lo] + (vals[hi] - vals[lo]) * frac


def load_offered_rps(run_dir: Path) -> float | None:
    rows = read_csv_rows(run_dir / "open_loop_arrival_1s_summary.csv")
    vals = [f(row, "offered_rps", float("nan")) for row in rows]
    vals = [v for v in vals if math.isfinite(v)]
    return percentile(vals, 0.5)


def classify_feature(name: str) -> str:
    lower = name.lower()
    if any(lower.startswith(prefix) for prefix in EXCLUDE_PREFIXES) or any(token in lower for token in EXCLUDE_SUBSTRINGS):
        return "metadata_or_debug"
    if "disk_" in lower or "filesystem" in lower:
        return "storage_context"
    if "sample_age" in lower or "query_duration" in lower or "collector" in lower:
        return "telemetry_quality"
    if "energy_mj_sum" in lower:
        return "thermal_clock_power_context"
    if any(token in lower for token in ("gpu_util", "gpu_compute.gpu_util", "gpu_pressure", "schedulable_gpu")):
        return "gpu_load_candidate"
    if any(token in lower for token in ("fb_used", "vram", "memory.used", "memory_working_set", "mem_used", "ram_capacity", "memcap")):
        return "memory_load_candidate"
    if any(token in lower for token in ("cpu_usage", "cpu_used", "cpu_cores_rate", "cpu_system", "cpu_user", "load1", "load5", "load15")):
        return "cpu_load_candidate"
    if any(token in lower for token in ("temp", "clock", "power_watts", "power.draw", "pstate", "thermal_violation", "power_violation")):
        return "thermal_clock_power_context"
    if any(token in lower for token in ("pods_running", "pods_ready", "gpu_pods", "deployments", "workloads")):
        return "service_cluster_context"
    return "other_numeric_candidate"


def candidate_decision(role: str, missing_rate: float, unique_count: int, std: float | None) -> str:
    if role in {"metadata_or_debug", "telemetry_quality"}:
        return "exclude_primary_feature"
    if role in {"thermal_clock_power_context", "storage_context"}:
        return "target_or_context_not_external_load"
    if missing_rate > 0.2:
        return "exclude_missing"
    if unique_count <= 1 or std is None or std == 0:
        return "exclude_constant"
    if role in {"gpu_load_candidate", "memory_load_candidate", "cpu_load_candidate"}:
        return "candidate_load_feature"
    return "candidate_context_feature"


def summarize_run(run_dir: Path) -> pd.DataFrame:
    vm_path = run_dir / "vm_aggregator_timeseries.csv"
    if not vm_path.exists():
        return pd.DataFrame()
    df = pd.read_csv(vm_path)
    offered = load_offered_rps(run_dir)
    df["__run_dir"] = str(run_dir)
    df["__offered_rps"] = offered
    df["__elapsed_row"] = range(len(df))
    return df


def build_summary(all_df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    feature_cols = [c for c in all_df.columns if c.startswith("vmagg.")]
    offered = pd.to_numeric(all_df["__offered_rps"], errors="coerce")
    for col in feature_cols:
        numeric = pd.to_numeric(all_df[col], errors="coerce")
        non_missing = int(numeric.notna().sum())
        total = int(len(numeric))
        missing_rate = 1.0 - (non_missing / total if total else 0.0)
        vals = numeric.dropna()
        std = float(vals.std()) if len(vals) > 1 and math.isfinite(float(vals.std())) else None
        role = classify_feature(col)
        corr = pearson(offered.tolist(), numeric.tolist())
        by_level = []
        for rps, group in all_df.assign(__feature=numeric).groupby("__offered_rps"):
            gv = pd.to_numeric(group["__feature"], errors="coerce").dropna()
            by_level.append(f"{rps}:{float(gv.median()) if len(gv) else 'nan'}")
        rows.append(
            {
                "feature": col,
                "role": role,
                "decision": candidate_decision(role, missing_rate, int(vals.nunique()), std),
                "rows": total,
                "non_missing": non_missing,
                "missing_rate": missing_rate,
                "unique_count": int(vals.nunique()),
                "mean": float(vals.mean()) if len(vals) else None,
                "median": float(vals.median()) if len(vals) else None,
                "std": std,
                "min": float(vals.min()) if len(vals) else None,
                "max": float(vals.max()) if len(vals) else None,
                "pearson_with_offered_rps": corr,
                "median_by_offered_rps": "; ".join(by_level),
            }
        )
    return rows


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: List[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_report(out_dir: Path, input_root: Path, summary: List[Dict[str, Any]], manifest: Dict[str, Any]) -> None:
    candidates = [r for r in summary if r["decision"] == "candidate_load_feature"]
    candidates = sorted(
        candidates,
        key=lambda r: (
            abs(float(r["pearson_with_offered_rps"])) if r.get("pearson_with_offered_rps") is not None else -1.0,
            float(r.get("std") or 0.0),
        ),
        reverse=True,
    )
    context = [r for r in summary if r["decision"] == "target_or_context_not_external_load"]
    context = sorted(context, key=lambda r: float(r.get("std") or 0.0), reverse=True)

    lines = [
        "# VM-derived telemetry feature candidate check",
        "",
        f"- input_root: `{input_root}`",
        f"- calibration_runs: `{manifest['runs']}`",
        f"- rows: `{manifest['rows']}`",
        f"- numeric_vmagg_features: `{manifest['numeric_vmagg_features']}`",
        f"- candidate_load_features: `{len(candidates)}`",
        "",
        "此檢查只用 normal-cooling calibration first pass。它用來判斷 VM-derived telemetry 是否可進入下一階段 load-conditioned model 的候選特徵，不代表已完成 feature importance，也不代表未知根因泛化。",
        "",
        "## Recommended Load Candidates",
        "",
        "| feature | role | missing | unique | corr_with_offered_rps | median_by_offered_rps |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in candidates[:20]:
        lines.append(
            f"| `{row['feature']}` | `{row['role']}` | {row['missing_rate']:.3f} | {row['unique_count']} | {row.get('pearson_with_offered_rps')} | `{row.get('median_by_offered_rps')}` |"
        )
    lines.extend(
        [
            "",
            "## Target / Context Signals",
            "",
            "以下欄位可作為 thermal/clock/power target 或 context，但不應與 offered load 混為同一類外部 demand feature。",
            "",
            "| feature | missing | median_by_offered_rps |",
            "|---|---:|---|",
        ]
    )
    for row in context[:20]:
        lines.append(f"| `{row['feature']}` | {row['missing_rate']:.3f} | `{row.get('median_by_offered_rps')}` |")
    lines.extend(
        [
            "",
            "## Method Notes",
            "",
            "- External demand 仍以 open-loop `offered_rps` / scheduled arrivals 為準。",
            "- `completed RPS`、success rate、latency history 屬 observed service state，不可取代 offered load。",
            "- fan mode、phase、run ID、cycle ID、absolute elapsed time 不列入 primary operational features。",
            "- 目前只有 3 個 short calibration levels；相關係數只作 sanity check，不作正式 feature importance。",
        ]
    )
    (out_dir / "vm_feature_candidate_report_zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    input_root = Path(args.input_root)
    out_dir = Path(args.out_dir)
    run_dirs = [
        p
        for p in sorted(input_root.iterdir())
        if p.is_dir() and (p / "vm_aggregator_timeseries.csv").exists() and (p / "open_loop_arrival_1s_summary.csv").exists()
    ]
    frames = [summarize_run(run_dir) for run_dir in run_dirs]
    frames = [df for df in frames if not df.empty]
    if not frames:
        raise RuntimeError(f"no calibration run dirs with vm_aggregator_timeseries.csv under {input_root}")
    all_df = pd.concat(frames, ignore_index=True)
    summary = build_summary(all_df)
    write_csv(out_dir / "vm_feature_candidate_summary.csv", summary)
    candidate_count = sum(1 for row in summary if row["decision"] == "candidate_load_feature")
    manifest = {
        "input_root": str(input_root),
        "runs": len(run_dirs),
        "rows": int(len(all_df)),
        "numeric_vmagg_features": len(summary),
        "candidate_load_features": candidate_count,
        "notes": "correlations are calibration sanity checks only; not formal feature importance",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(out_dir, input_root, summary, manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root", required=True)
    p.add_argument("--out-dir", required=True)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
