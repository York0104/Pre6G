#!/usr/bin/env python3
"""Analyze VictoriaMetrics query sample age sidecar for open-loop runs."""

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


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def percentile(values: Iterable[float], q: float) -> float | None:
    vals = sorted(v for v in values if math.isfinite(v))
    if not vals:
        return None
    idx = (len(vals) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(vals) - 1)
    frac = idx - lo
    return vals[lo] + (vals[hi] - vals[lo]) * frac


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return rows


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


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


def compact_promql(promql: str, max_len: int = 140) -> str:
    text = " ".join((promql or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def promql_metric_hint(promql: str) -> str:
    match = re.search(r"([A-Za-z_:][A-Za-z0-9_:]*)\s*(?:\{|$|\[)", promql or "")
    return match.group(1) if match else ""


def classify_age(max_age_s: float | None, strict_s: float, caution_s: float) -> str:
    if max_age_s is None:
        return "missing"
    if max_age_s <= strict_s:
        return "ok_for_10_30s_warning"
    if max_age_s <= caution_s:
        return "caution_for_10_30s_warning"
    return "not_primary_for_10_30s_warning"


def analyze_sidecar(path: Path, strict_s: float, caution_s: float) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    rows = read_jsonl(path)
    by_query: Dict[int, Dict[str, Any]] = {}
    ages_by_query: Dict[int, List[float]] = defaultdict(list)
    qdur_by_query: Dict[int, List[float]] = defaultdict(list)
    timeline: List[Dict[str, Any]] = []
    missing_ts = 0
    error_count = 0
    total_samples = 0

    for collector_idx, row in enumerate(rows):
        collector_ts = row.get("ts", "")
        samples = row.get("samples") or []
        for sample in samples:
            total_samples += 1
            qidx = int(sample.get("query_index") or 0)
            promql = str(sample.get("promql") or "")
            by_query.setdefault(
                qidx,
                {
                    "query_index": qidx,
                    "metric_hint": promql_metric_hint(promql),
                    "promql": compact_promql(promql),
                    "result_count_min": None,
                    "result_count_max": None,
                    "error_count": 0,
                    "missing_sample_ts_count": 0,
                },
            )
            base = by_query[qidx]
            result_count = safe_float(sample.get("result_count"))
            if result_count is not None:
                base["result_count_min"] = result_count if base["result_count_min"] is None else min(base["result_count_min"], result_count)
                base["result_count_max"] = result_count if base["result_count_max"] is None else max(base["result_count_max"], result_count)
            if sample.get("error"):
                base["error_count"] += 1
                error_count += 1
            if sample.get("sample_ts_max") is None:
                base["missing_sample_ts_count"] += 1
                missing_ts += 1
            age = safe_float(sample.get("sample_age_max_s"))
            qdur = safe_float(sample.get("query_duration_s"))
            if age is not None:
                ages_by_query[qidx].append(age)
            if qdur is not None:
                qdur_by_query[qidx].append(qdur)
            timeline.append(
                {
                    "collector_index": collector_idx,
                    "collector_ts": collector_ts,
                    "query_index": qidx,
                    "metric_hint": base["metric_hint"],
                    "sample_age_max_s": age,
                    "query_duration_s": qdur,
                    "result_count": result_count,
                    "error": sample.get("error", ""),
                    "decision": classify_age(age, strict_s, caution_s),
                }
            )

    summary_rows: List[Dict[str, Any]] = []
    all_ages: List[float] = []
    for qidx, base in sorted(by_query.items()):
        ages = ages_by_query.get(qidx, [])
        qdurs = qdur_by_query.get(qidx, [])
        all_ages.extend(ages)
        max_age = max(ages) if ages else None
        summary_rows.append(
            {
                **base,
                "observations": len(ages),
                "sample_age_p50_s": percentile(ages, 0.5),
                "sample_age_p95_s": percentile(ages, 0.95),
                "sample_age_max_s": max_age,
                "query_duration_p50_s": percentile(qdurs, 0.5),
                "query_duration_p95_s": percentile(qdurs, 0.95),
                "query_duration_max_s": max(qdurs) if qdurs else None,
                "decision": classify_age(max_age, strict_s, caution_s),
            }
        )

    manifest = {
        "sidecar": str(path),
        "collector_rows": len(rows),
        "query_observations": total_samples,
        "query_count": len(by_query),
        "query_errors": error_count,
        "missing_sample_ts_count": missing_ts,
        "overall_sample_age_p50_s": percentile(all_ages, 0.5),
        "overall_sample_age_p95_s": percentile(all_ages, 0.95),
        "overall_sample_age_max_s": max(all_ages) if all_ages else None,
        "strict_age_threshold_s": strict_s,
        "caution_age_threshold_s": caution_s,
        "overall_decision": classify_age(max(all_ages) if all_ages else None, strict_s, caution_s),
    }
    return summary_rows, timeline, manifest


def csv_debug_age_summary(path: Path) -> Dict[str, Any]:
    rows = read_csv(path)
    if not rows:
        return {"csv_path": str(path), "rows": 0}
    age_cols = [
        c
        for c in rows[0]
        if re.search(r"(?:^|[._])sample_age_(?:min|p50|p95|max|max_max|maximum)[._a-z]*_s$", c)
        or re.search(r"(?:^|[._])sample_age_max_(?:min|p50|p95|max)_s$", c)
    ]
    out: Dict[str, Any] = {"csv_path": str(path), "rows": len(rows), "age_columns": age_cols}
    for col in age_cols:
        vals = [safe_float(row.get(col)) for row in rows]
        nums = [v for v in vals if v is not None]
        out[f"{col}.p50"] = percentile(nums, 0.5)
        out[f"{col}.p95"] = percentile(nums, 0.95)
        out[f"{col}.max"] = max(nums) if nums else None
    return out


def write_report(out_dir: Path, run_dir: Path, manifest: Dict[str, Any], csv_debug: Dict[str, Any], top_queries: List[Dict[str, Any]]) -> None:
    decision = manifest.get("overall_decision")
    max_age = manifest.get("overall_sample_age_max_s")
    p95_age = manifest.get("overall_sample_age_p95_s")
    lines = [
        "# VM sample-age analysis",
        "",
        f"- run_dir: `{run_dir}`",
        f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`",
        f"- collector rows: `{manifest.get('collector_rows')}`",
        f"- query observations: `{manifest.get('query_observations')}`",
        f"- missing sample timestamp count: `{manifest.get('missing_sample_ts_count')}`",
        f"- query errors: `{manifest.get('query_errors')}`",
        f"- overall sample-age p95 / max: `{p95_age}` / `{max_age}` seconds",
        f"- decision: `{decision}`",
        "",
        "## 判讀",
        "",
    ]
    if decision == "ok_for_10_30s_warning":
        lines.append("本次 sidecar per-query sample timestamp 顯示 VM instant query 的 sample age 足夠新，可作為 10-30 秒 early-warning 的候選 auxiliary/primary telemetry feature。")
    elif decision == "caution_for_10_30s_warning":
        lines.append("本次 VM sample age 進入 caution 區間；若用於 10-30 秒 early-warning，需以 sample_age filter 或 sensitivity analysis 控制。")
    else:
        lines.append("本次 VM sample age 不適合作為 10-30 秒 early-warning 的 primary telemetry feature；可先保留 request log 與 nvidia-smi 作主要資料鏈。")
    lines.extend(
        [
            "",
            "CSV debug 欄位只納入真正的 `sample_age_*_s` 欄位；`queries_recorded` 不可被解讀成 sample age 秒數。",
            "",
            "## Top Query Age",
            "",
            "| query_index | metric_hint | p95_s | max_s | decision |",
            "|---:|---|---:|---:|---|",
        ]
    )
    for row in top_queries[:12]:
        lines.append(
            f"| {row.get('query_index')} | `{row.get('metric_hint')}` | {row.get('sample_age_p95_s')} | {row.get('sample_age_max_s')} | `{row.get('decision')}` |"
        )
    lines.extend(
        [
            "",
            "## CSV Debug Cross-check",
            "",
            f"- csv rows: `{csv_debug.get('rows')}`",
            f"- age columns: `{csv_debug.get('age_columns')}`",
        ]
    )
    (out_dir / "vm_sample_age_report_zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    sidecar = Path(args.sidecar) if args.sidecar else run_dir / "vm_aggregator_timeseries.vm_query_samples.jsonl"
    csv_path = Path(args.vm_csv) if args.vm_csv else run_dir / "vm_aggregator_timeseries.csv"
    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "vm_sample_age_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows, timeline_rows, manifest = analyze_sidecar(sidecar, args.strict_age_s, args.caution_age_s)
    csv_debug = csv_debug_age_summary(csv_path)
    manifest["run_dir"] = str(run_dir)
    manifest["csv_debug"] = csv_debug

    write_csv(out_dir / "vm_sample_age_per_query_summary.csv", summary_rows)
    write_csv(out_dir / "vm_sample_age_timeline.csv", timeline_rows)
    top_queries = sorted(summary_rows, key=lambda row: safe_float(row.get("sample_age_max_s")) or -1.0, reverse=True)
    write_report(out_dir, run_dir, manifest, csv_debug, top_queries)
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--sidecar")
    p.add_argument("--vm-csv")
    p.add_argument("--out-dir")
    p.add_argument("--strict-age-s", type=float, default=5.0)
    p.add_argument("--caution-age-s", type=float, default=30.0)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
