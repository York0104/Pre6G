#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


DEFAULT_RESULTS_ROOT = Path(
    "autoscale-source-split/02-experiment-layer/experiments_yolo/results/single_pod_bgload_fan_cycle"
)
DEFAULT_OUT_NAME = "vm_load_forecasting_analysis"
HORIZONS_S = [10, 30, 60]
ROLL_WINDOWS_S = [5, 15, 60]

TARGET_SPECS = {
    "gpu_util_percent": [
        "node.gpu_feat.gpu.gpu_util_avg",
        "node.gpu_pressure.gpus[0].gpu_util",
    ],
    "vram_used_percent": [
        "node.gpu_feat.vram.fb_used_percent_avg",
        "node.gpu_pressure.gpus[0].fb_used_percent",
    ],
    "cpu_usage_percent": [
        "node.node_feat.cpu.cpu_usage_percent",
        "node.node_pressure.cpu_usage_percent",
        "node.node_inst.cpu_usage_percent",
    ],
    "ram_usage_percent": [
        "node.node_feat.ram.memory_usage_percent",
        "node.node_pressure.memory_usage_percent",
        "node.node_inst.memory_usage_percent",
    ],
}


def run_complete(run_dir: Path) -> tuple[bool, str]:
    required = [
        "time_window.txt",
        "measurement_raw.csv",
        "nvidia_smi_gpu_1s.csv",
        "vm_aggregator_training_features.csv",
    ]
    missing = [name for name in required if not (run_dir / name).exists()]
    if missing:
        return False, "missing " + ",".join(missing)
    text = (run_dir / "time_window.txt").read_text(encoding="utf-8", errors="replace")
    if "END_EPOCH=" not in text:
        return False, "time_window_missing_END_EPOCH"
    return True, ""


def choose_col(cols: list[str], candidates: list[str]) -> str | None:
    for col in candidates:
        if col in cols:
            return col
    return None


def discover_runs(results_root: Path) -> pd.DataFrame:
    rows = []
    for run_dir in sorted(p for p in results_root.iterdir() if p.is_dir()):
        if not run_dir.name.startswith("singlepod_bgcycle_"):
            continue
        ok, reason = run_complete(run_dir)
        rows.append(
            {
                "run_id": run_dir.name,
                "run_dir": str(run_dir),
                "complete": ok,
                "exclude_reason": reason,
                "vm_aggregator_training_features": str(run_dir / "vm_aggregator_training_features.csv"),
                "vm_aggregator_timeseries": str(run_dir / "vm_aggregator_timeseries.csv"),
            }
        )
    return pd.DataFrame(rows)


def load_vm_sample_age(run_dir: Path) -> dict[str, float | str | int]:
    path = run_dir / "vm_aggregator_timeseries.csv"
    out: dict[str, float | str | int] = {
        "run_id": run_dir.name,
        "has_vm_sample_age": 0,
        "vm_sample_age_max_p50_s_median": math.nan,
        "vm_sample_age_max_p95_s_median": math.nan,
        "vm_sample_age_max_max_s_max": math.nan,
    }
    if not path.exists():
        return out
    usecols = [
        "vmagg._debug.vm_query_sample_age_summary.sample_age_max_p50_s",
        "vmagg._debug.vm_query_sample_age_summary.sample_age_max_p95_s",
        "vmagg._debug.vm_query_sample_age_summary.sample_age_max_max_s",
    ]
    try:
        df = pd.read_csv(path, usecols=lambda c: c in usecols, low_memory=False)
    except Exception:
        return out
    if df.empty or not set(usecols).intersection(df.columns):
        return out
    out["has_vm_sample_age"] = 1
    for col in usecols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    p50 = usecols[0]
    p95 = usecols[1]
    pmax = usecols[2]
    out["vm_sample_age_max_p50_s_median"] = float(df[p50].median()) if p50 in df else math.nan
    out["vm_sample_age_max_p95_s_median"] = float(df[p95].median()) if p95 in df else math.nan
    out["vm_sample_age_max_max_s_max"] = float(df[pmax].max()) if pmax in df else math.nan
    return out


def load_dataset(inv: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    mapping_rows = []
    for row in inv[inv["complete"]].itertuples(index=False):
        path = Path(row.vm_aggregator_training_features)
        df = pd.read_csv(path, low_memory=False)
        df["run_id"] = row.run_id
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
        df = df.dropna(subset=["ts"]).sort_values("ts")
        df["elapsed_s"] = (df["ts"] - df["ts"].iloc[0]).dt.total_seconds()
        cols = list(df.columns)
        for target, candidates in TARGET_SPECS.items():
            source = choose_col(cols, candidates)
            mapping_rows.append({"run_id": row.run_id, "target": target, "source_column": source or ""})
            df[target] = pd.to_numeric(df[source], errors="coerce") if source else np.nan
        frames.append(df)
    if not frames:
        return pd.DataFrame(), pd.DataFrame(mapping_rows)
    data = pd.concat(frames, ignore_index=True)
    return data, pd.DataFrame(mapping_rows)


def add_past_features(data: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = data.copy()
    base_targets = list(TARGET_SPECS.keys())
    features = ["elapsed_s"]
    for col in base_targets:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        features.append(col)
        for lag in [1, 5, 15, 30, 60]:
            name = f"{col}_lag_{lag}s"
            df[name] = df.groupby("run_id", group_keys=False)[col].shift(lag)
            features.append(name)
        for win in ROLL_WINDOWS_S:
            mean_name = f"{col}_roll_mean_{win}s"
            std_name = f"{col}_roll_std_{win}s"
            slope_name = f"{col}_slope_{win}s"
            grouped = df.groupby("run_id", group_keys=False)[col]
            df[mean_name] = grouped.transform(lambda s, w=win: s.rolling(w, min_periods=max(2, w // 3)).mean())
            df[std_name] = grouped.transform(lambda s, w=win: s.rolling(w, min_periods=max(2, w // 3)).std())
            df[slope_name] = (df[col] - grouped.shift(win)) / float(win)
            features.extend([mean_name, std_name, slope_name])
    return df, features


def chrono_split(run_ids: list[str]) -> tuple[list[str], list[str]]:
    ordered = sorted(run_ids)
    n_test = max(1, int(math.ceil(len(ordered) * 0.2)))
    if len(ordered) <= 2:
        n_test = 1
    return ordered[:-n_test], ordered[-n_test:]


def ewma_forecast(train_df: pd.DataFrame, test_df: pd.DataFrame, target: str, horizon: int) -> pd.Series:
    del train_df, horizon
    return test_df.groupby("run_id", group_keys=False)[target].transform(
        lambda s: s.ewm(span=15, adjust=False, min_periods=1).mean()
    )


def evaluate(data: pd.DataFrame, features: list[str], out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    run_ids = sorted(data["run_id"].dropna().unique().tolist())
    train_runs, test_runs = chrono_split(run_ids)
    (out_dir / "validation_split.json").write_text(
        json.dumps(
            {
                "split": "chronological group split by RUN_ID",
                "train_runs": train_runs,
                "test_runs": test_runs,
                "no_random_row_split": True,
                "future_leakage_controls": [
                    "features use current and past values only",
                    "targets are future shifts within each run",
                    "same run is not split across train/test",
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rows = []
    timeline = []
    importance = []
    for target in TARGET_SPECS:
        for horizon in HORIZONS_S:
            work = data.copy()
            work["y_future"] = work.groupby("run_id", group_keys=False)[target].shift(-horizon)
            needed = list(dict.fromkeys(["run_id", "ts", "elapsed_s", target, "y_future"] + features))
            model_df = work[needed].dropna(subset=[target, "y_future"])
            train = model_df[model_df["run_id"].isin(train_runs)].copy()
            test = model_df[model_df["run_id"].isin(test_runs)].copy()
            if len(train) < 100 or len(test) < 20:
                rows.append(
                    {
                        "target": target,
                        "horizon_s": horizon,
                        "model": "insufficient_data",
                        "train_rows": len(train),
                        "test_rows": len(test),
                    }
                )
                continue
            X_train = train[features]
            y_train = train["y_future"]
            X_test = test[features]
            y_test = test["y_future"]
            preds = {
                "persistence": pd.to_numeric(test[target], errors="coerce").to_numpy(),
                "ewma": ewma_forecast(train, test, target, horizon).to_numpy(),
            }
            linear = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0))
            linear.fit(X_train, y_train)
            preds["linear_ar_ridge"] = linear.predict(X_test)
            hgb = make_pipeline(
                SimpleImputer(strategy="median"),
                HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, l2_regularization=0.1, random_state=7),
            )
            hgb.fit(X_train, y_train)
            preds["hist_gradient_boosting"] = hgb.predict(X_test)

            for model, y_pred in preds.items():
                mask = np.isfinite(y_pred) & np.isfinite(y_test.to_numpy())
                if mask.sum() == 0:
                    continue
                err = y_test.to_numpy()[mask] - y_pred[mask]
                mse = mean_squared_error(y_test.to_numpy()[mask], y_pred[mask])
                rows.append(
                    {
                        "target": target,
                        "horizon_s": horizon,
                        "model": model,
                        "train_rows": len(train),
                        "test_rows": len(test),
                        "mae": float(mean_absolute_error(y_test.to_numpy()[mask], y_pred[mask])),
                        "rmse": float(math.sqrt(mse)),
                        "r2": float(r2_score(y_test.to_numpy()[mask], y_pred[mask])),
                        "bias": float(np.mean(err)),
                    }
                )
            keep = test[["run_id", "ts", "elapsed_s", target, "y_future"]].copy()
            keep["target"] = target
            keep["horizon_s"] = horizon
            for model, y_pred in preds.items():
                keep[f"pred_{model}"] = y_pred
            timeline.append(keep)

            ridge = linear.named_steps["ridge"]
            coefs = ridge.coef_
            for feat, coef in sorted(zip(features, coefs), key=lambda x: abs(x[1]), reverse=True)[:30]:
                importance.append(
                    {
                        "target": target,
                        "horizon_s": horizon,
                        "model": "linear_ar_ridge",
                        "feature": feat,
                        "coefficient": float(coef),
                        "abs_coefficient": float(abs(coef)),
                    }
                )
    eval_df = pd.DataFrame(rows)
    timeline_df = pd.concat(timeline, ignore_index=True) if timeline else pd.DataFrame()
    importance_df = pd.DataFrame(importance)
    eval_df.to_csv(out_dir / "load_forecast_model_evaluation.csv", index=False)
    timeline_df.to_csv(out_dir / "load_forecast_heldout_timeline.csv", index=False)
    importance_df.to_csv(out_dir / "load_forecast_feature_coefficients.csv", index=False)
    return eval_df, timeline_df, importance_df


def plot_outputs(data: pd.DataFrame, eval_df: pd.DataFrame, timeline: pd.DataFrame, out_dir: Path) -> None:
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(exist_ok=True)
    if not data.empty:
        run_id = sorted(data["run_id"].unique())[-1]
        d = data[data["run_id"].eq(run_id)]
        fig, axes = plt.subplots(4, 1, figsize=(13, 9), sharex=True)
        for ax, target in zip(axes, TARGET_SPECS):
            ax.plot(d["elapsed_s"], d[target], lw=1.0)
            ax.set_ylabel(target)
            ax.grid(alpha=0.25)
        axes[-1].set_xlabel("elapsed seconds")
        fig.suptitle(f"VM load signals: {run_id}")
        fig.tight_layout()
        fig.savefig(fig_dir / "vm_load_timeseries.png", dpi=170)
        plt.close(fig)
    if not eval_df.empty:
        pivot = eval_df.pivot_table(index=["target", "horizon_s"], columns="model", values="mae", aggfunc="first")
        fig, ax = plt.subplots(figsize=(12, max(4, len(pivot) * 0.35)))
        pivot.plot(kind="barh", ax=ax)
        ax.set_xlabel("MAE")
        ax.set_title("Held-out load forecast MAE")
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        fig.savefig(fig_dir / "load_forecast_model_performance.png", dpi=170)
        plt.close(fig)
    if not timeline.empty:
        for target in TARGET_SPECS:
            d = timeline[(timeline["target"].eq(target)) & (timeline["horizon_s"].eq(30))]
            if d.empty:
                continue
            run_id = sorted(d["run_id"].unique())[-1]
            d = d[d["run_id"].eq(run_id)].tail(1200)
            fig, ax = plt.subplots(figsize=(13, 4))
            ax.plot(d["elapsed_s"], d["y_future"], label="observed future", lw=1.1)
            for col in ["pred_persistence", "pred_ewma", "pred_linear_ar_ridge", "pred_hist_gradient_boosting"]:
                if col in d:
                    ax.plot(d["elapsed_s"], d[col], label=col.replace("pred_", ""), lw=0.9, alpha=0.85)
            ax.set_title(f"{target} forecast vs observed, H=30s")
            ax.set_xlabel("elapsed seconds")
            ax.set_ylabel(target)
            ax.grid(alpha=0.25)
            ax.legend(ncol=2, fontsize=8)
            fig.tight_layout()
            fig.savefig(fig_dir / f"forecast_vs_observed_{target}_h30.png", dpi=170)
            plt.close(fig)


def markdown_table(df: pd.DataFrame, cols: list[str]) -> str:
    if df.empty:
        return ""
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for row in df[cols].itertuples(index=False):
        vals = []
        for v in row:
            if isinstance(v, float):
                vals.append(f"{v:.6g}")
            else:
                vals.append(str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def write_report(
    out_dir: Path,
    inv: pd.DataFrame,
    source_map: pd.DataFrame,
    age_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    importance: pd.DataFrame,
) -> None:
    complete = inv[inv["complete"]]
    excluded = inv[~inv["complete"]]
    best = pd.DataFrame()
    if not eval_df.empty and "mae" in eval_df:
        best = eval_df.sort_values("mae").groupby(["target", "horizon_s"], as_index=False).first()
    lines = [
        "# VM 主要負載指標短期預測分析",
        "",
        "## 資料範圍",
        "",
        f"- discovered runs：{len(inv)}",
        f"- completed runs used for modeling：{len(complete)}",
        f"- excluded / incomplete runs：{len(excluded)}",
        "- validation：chronological group split by RUN_ID；未使用 random row split。",
        "- features：僅使用 t 時刻與過去 rolling / lag 特徵，target 使用同一 run 內 future shift。",
        "",
        "## 主要預測 target",
        "",
    ]
    for target in TARGET_SPECS:
        src = source_map[source_map["target"].eq(target)]["source_column"].dropna()
        src = src[src.ne("")]
        top_src = src.value_counts().index[0] if len(src) else "not available"
        lines.append(f"- {target}：{top_src}")
    lines.extend(
        [
            "",
            "## VM sample age audit",
            "",
            "VM sample age 欄位用於資料品質審計，不作為模型 feature。",
        ]
    )
    if not age_df.empty and "has_vm_sample_age" in age_df:
        lines.append(
            f"- runs with sample-age metadata：{int(age_df['has_vm_sample_age'].sum())} / {len(age_df)}"
        )
        if age_df["has_vm_sample_age"].sum():
            lines.append(
                "- median p95 sample age across runs："
                f"{age_df['vm_sample_age_max_p95_s_median'].median():.3f} s"
            )
    lines.extend(["", "## Held-out forecasting 結果", ""])
    if best.empty:
        lines.append("資料不足，無法完成模型評估。")
    else:
        lines.append(markdown_table(best, ["target", "horizon_s", "model", "mae", "rmse", "r2", "bias"]))
    lines.extend(
        [
            "",
            "## 方法學解讀",
            "",
            "- 這一層回答的是 CPU / GPU / VRAM / RAM 等負載 telemetry 是否具有短期可預測性。",
            "- 這不是熱衰減分類器，也沒有使用 phase、fan mode、intervention flag、run ID 或 cycle ID 作 primary feature。",
            "- 若負載預測 residual 在 thermal / clock / latency 劣化前穩定偏離，才適合進一步接到 thermal-performance anomaly detection。",
            "- 目前資料仍多來自相同 fan-cycle 實驗模板，因此結果只能視為同環境探索，不可宣稱未知根因泛化。",
            "",
            "## 下一步",
            "",
            "1. 用 load forecast residual 建立 CPU/GPU/VRAM/RAM 多指標異常分數。",
            "2. 將負載 residual 與 GPU temperature / SM clock / service degradation onset 做事件對齊。",
            "3. 比較 thermal-only、load-only、thermal+load 三種 early-warning feature set。",
            "4. 若 VM-derived telemetry 要成為 primary feature，持續保留 sample timestamp / age 欄位。",
        ]
    )
    (out_dir / "vm_load_forecasting_report_zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/pre6g_matplotlib")
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()
    out_dir = args.out_dir or (args.results_root / DEFAULT_OUT_NAME)
    out_dir.mkdir(parents=True, exist_ok=True)
    inv = discover_runs(args.results_root)
    inv.to_csv(out_dir / "load_run_inventory.csv", index=False)
    age_rows = [load_vm_sample_age(Path(row.run_dir)) for row in inv[inv["complete"]].itertuples(index=False)]
    age_df = pd.DataFrame(age_rows)
    age_df.to_csv(out_dir / "vm_sample_age_quality_summary.csv", index=False)
    data, source_map = load_dataset(inv)
    source_map.to_csv(out_dir / "load_target_source_columns.csv", index=False)
    if data.empty:
        raise RuntimeError("no completed vm_aggregator_training_features.csv files available")
    data, features = add_past_features(data)
    data.to_csv(out_dir / "vm_load_aligned_features.csv", index=False)
    eval_df, timeline, importance = evaluate(data, features, out_dir)
    plot_outputs(data, eval_df, timeline, out_dir)
    write_report(out_dir, inv, source_map, age_df, eval_df, importance)
    manifest = {
        "analysis_name": "offline_vm_load_forecasting",
        "results_root": str(args.results_root),
        "out_dir": str(out_dir),
        "targets": TARGET_SPECS,
        "horizons_s": HORIZONS_S,
        "roll_windows_s": ROLL_WINDOWS_S,
        "no_random_row_split": True,
        "primary_control_metadata_excluded": True,
        "completed_runs_used": int(inv["complete"].sum()) if "complete" in inv else 0,
        "excluded_runs": int((~inv["complete"]).sum()) if "complete" in inv else 0,
        "outputs": sorted(str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file()),
    }
    (out_dir / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] wrote VM load forecasting analysis to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
