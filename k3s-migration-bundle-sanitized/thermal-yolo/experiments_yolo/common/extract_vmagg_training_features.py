#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


DROP_PREFIXES = (
    "vmagg._debug.",
)

DROP_EXACT = {
    "collector_error",
    "vmagg.collector_error",
}

KEEP_BASE = [
    "ts",
    "collector_elapsed_s",
    "collector_ok",
    "monitor_node",
    "monitor_namespace",
]

GPU_LIST_COL = "vmagg.target_node_semantic.gpu_pressure.gpus"


def flatten_json(obj, prefix="", out=None):
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            flatten_json(v, key, out)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            key = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
            flatten_json(item, key, out)
    else:
        out[prefix] = obj
    return out


def expand_gpu_list_columns(df: pd.DataFrame) -> pd.DataFrame:
    if GPU_LIST_COL not in df.columns:
        return df

    expanded_rows = []
    all_keys = set()
    series = df[GPU_LIST_COL].fillna("")
    for raw in series:
        expanded = {}
        text = str(raw).strip()
        if text and text not in {"[]", "null", "None"}:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    expanded = flatten_json(parsed, prefix=GPU_LIST_COL)
            except Exception:
                expanded = {}
        expanded_rows.append(expanded)
        all_keys.update(expanded.keys())

    for key in sorted(all_keys):
        df[key] = [row.get(key) for row in expanded_rows]

    return df


def should_drop_column(name: str) -> bool:
    if name in DROP_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in DROP_PREFIXES)


def shorten_column(name: str) -> str:
    out = name
    replacements = [
        ("vmagg.", ""),
        ("cluster_semantic.", "cluster."),
        ("target_node_semantic.", "node."),
        ("namespace_total.", "ns_total."),
        ("pods_phase_counts.", "pod_phase."),
        ("node_pressure_instant.", "node_inst."),
        ("node_pressure.", "node_pressure."),
        ("node_compute_features.", "node_feat."),
        ("gpu_bound_features.", "gpu_feat."),
        ("gpu_pressure.", "gpu_pressure."),
        ("cpu_compute.", "cpu."),
        ("ram_capacity.", "ram."),
        ("data_movement.", "io."),
        ("gpu_compute.", "gpu."),
        ("vram_capacity.", "vram."),
        ("memory_capacity.", "memcap."),
        ("memory_bandwidth_proxy.", "mem_bw."),
        ("compute_proxy.", "gpu_proxy."),
        ("thermal_power_health.", "thermal."),
    ]
    for src, dst in replacements:
        out = out.replace(src, dst)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="path to vm_aggregator_timeseries.csv")
    ap.add_argument("--out", default="", help="output csv path")
    ap.add_argument(
        "--keep-non-numeric",
        action="store_true",
        help="keep non-numeric vmagg columns instead of dropping them",
    )
    args = ap.parse_args()

    in_path = Path(args.input).expanduser().resolve()
    if not in_path.exists():
        raise FileNotFoundError(f"missing input csv: {in_path}")

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
    else:
        out_path = in_path.with_name("vm_aggregator_training_features.csv")

    df = pd.read_csv(in_path)
    df = expand_gpu_list_columns(df)

    keep_cols = []
    for col in df.columns:
        if col in KEEP_BASE:
            keep_cols.append(col)
            continue
        if not col.startswith("vmagg."):
            continue
        if should_drop_column(col):
            continue
        keep_cols.append(col)

    work = df[keep_cols].copy()

    numeric_vmagg_cols = []
    dropped_non_numeric = []
    for col in list(work.columns):
        if col in KEEP_BASE:
            continue
        converted = pd.to_numeric(work[col], errors="coerce")
        non_null_original = work[col].notna().sum()
        non_null_converted = converted.notna().sum()

        if non_null_original == 0:
            work[col] = converted
            numeric_vmagg_cols.append(col)
            continue

        if non_null_converted == 0 and not args.keep_non_numeric:
            dropped_non_numeric.append(col)
            work = work.drop(columns=[col])
            continue

        if non_null_converted > 0:
            work[col] = converted
            numeric_vmagg_cols.append(col)

    rename_map = {col: shorten_column(col) for col in work.columns}
    work = work.rename(columns=rename_map)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    work.to_csv(out_path, index=False)

    summary = {
        "input": str(in_path),
        "output": str(out_path),
        "rows": int(len(work)),
        "cols": int(len(work.columns)),
        "kept_base_cols": [rename_map.get(c, c) for c in KEEP_BASE if c in rename_map],
        "numeric_feature_cols": int(
            sum(1 for c in work.columns if c not in {rename_map.get(x, x) for x in KEEP_BASE})
        ),
        "dropped_non_numeric_vmagg_cols": dropped_non_numeric,
    }

    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[OK] wrote training-ready csv: {out_path}")
    print(f"[OK] wrote summary: {summary_path}")
    print(f"[INFO] rows={summary['rows']} cols={summary['cols']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
