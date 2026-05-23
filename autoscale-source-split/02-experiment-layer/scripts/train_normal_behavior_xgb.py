#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.multioutput import MultiOutputRegressor

try:
    from xgboost import XGBRegressor
except Exception:
    XGBRegressor = None


CLIENT_FILES = {
    "focus_inst1.csv": "focus",
    "bg_inst2.csv": "bg2",
    "bg_inst3.csv": "bg3",
}

PREFERRED_TARGET_KEYWORDS = [
    "focus_client_latency_ms_p95",
    "focus_client_latency_ms_p99",
    "focus_client_latency_ms_mean",
    "focus_success_rate",
    "bg2_client_latency_ms_p95",
    "bg3_client_latency_ms_p95",
    "bg2_success_rate",
    "bg3_success_rate",
    "DCGM_FI_DEV_GPU_TEMP",
    "DCGM_FI_DEV_FB_USED_PERCENT",
    "DCGM_FI_DEV_MEM_COPY_UTIL",
    "DCGM_FI_DEV_SM_CLOCK",
    "DCGM_FI_DEV_MEM_CLOCK",
    "mem.available",
    "swap_used_bytes",
    "perf.instructions",
    "branch_misses",
    "cache_misses",
]


def find_ts_col(df):
    candidates = [
        "ts", "timestamp", "time", "datetime",
        "client_ts", "server_ts", "created_at", "date"
    ]
    lower_map = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c in df.columns:
            return c
        if c.lower() in lower_map:
            return lower_map[c.lower()]

    for c in df.columns[:8]:
        try:
            s = pd.to_datetime(df[c], errors="coerce")
            if s.notna().mean() > 0.7:
                return c
        except Exception:
            pass
    return None


def read_csv_time(path):
    df = pd.read_csv(path)
    ts_col = find_ts_col(df)
    if ts_col is None:
        raise ValueError(f"找不到時間欄位: {path}")

    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
    df = df.dropna(subset=[ts_col]).copy()
    df = df.sort_values(ts_col).set_index(ts_col)
    df.index.name = "ts"
    return df


def load_client_csv(path, label):
    df = read_csv_time(path)

    lat_col = None
    for c in ["latency_ms_client", "client_latency_ms", "latency_ms", "total_ms"]:
        if c in df.columns:
            lat_col = c
            break

    if lat_col is None:
        return pd.DataFrame()

    server_col = None
    for c in ["server_latency_ms", "infer_ms", "inference_ms"]:
        if c in df.columns:
            server_col = c
            break

    success_col = None
    for c in ["success", "ok"]:
        if c in df.columns:
            success_col = c
            break

    x = pd.DataFrame(index=df.index)
    x["lat"] = pd.to_numeric(df[lat_col], errors="coerce")

    if server_col:
        x["server_lat"] = pd.to_numeric(df[server_col], errors="coerce")
    else:
        x["server_lat"] = np.nan

    if success_col:
        s = df[success_col]
        if s.dtype == bool:
            x["success"] = s.astype(float)
        else:
            x["success"] = (
                s.astype(str)
                .str.lower()
                .isin(["true", "1", "yes", "ok"])
                .astype(float)
            )
    else:
        x["success"] = np.where(x["lat"].notna(), 1.0, 0.0)

    ok_lat = x["lat"].where(x["success"] >= 0.5)
    ok_server = x["server_lat"].where(x["success"] >= 0.5)

    out = pd.DataFrame()
    out[f"{label}_req_count"] = x["lat"].resample("1s").count()
    out[f"{label}_success_rate"] = x["success"].resample("1s").mean()
    out[f"{label}_client_latency_ms_mean"] = ok_lat.resample("1s").mean()
    out[f"{label}_client_latency_ms_p50"] = ok_lat.resample("1s").quantile(0.50)
    out[f"{label}_client_latency_ms_p95"] = ok_lat.resample("1s").quantile(0.95)
    out[f"{label}_client_latency_ms_p99"] = ok_lat.resample("1s").quantile(0.99)
    out[f"{label}_client_latency_ms_max"] = ok_lat.resample("1s").max()
    out[f"{label}_server_latency_ms_mean"] = ok_server.resample("1s").mean()
    out[f"{label}_server_latency_ms_p95"] = ok_server.resample("1s").quantile(0.95)

    return out


def load_aligned_metrics(run_dir):
    candidates = list(run_dir.rglob("aligned_metrics.csv"))
    if not candidates:
        return pd.DataFrame()

    path = candidates[0]

    try:
        df = read_csv_time(path)
    except Exception as e:
        print(f"[WARN] aligned_metrics.csv 讀取失敗: {path}: {e}", file=sys.stderr)
        return pd.DataFrame()

    num = df.apply(pd.to_numeric, errors="coerce")
    num = num.dropna(axis=1, how="all")

    if num.empty:
        return pd.DataFrame()

    num = num.resample("1s").mean()

    extra = {}
    for c in num.columns:
        lc = c.lower()
        if lc.endswith("_total") or "counter" in lc or "node_perf" in lc:
            extra[f"{c}_rate"] = num[c].diff().clip(lower=0)

    if extra:
        num = pd.concat([num, pd.DataFrame(extra, index=num.index)], axis=1)

    return num


def load_run(run_dir):
    frames = []

    m = load_aligned_metrics(run_dir)
    if not m.empty:
        frames.append(m)

    for filename, label in CLIENT_FILES.items():
        files = list(run_dir.rglob(filename))
        if files:
            try:
                cdf = load_client_csv(files[0], label)
                if not cdf.empty:
                    frames.append(cdf)
            except Exception as e:
                print(f"[WARN] client csv 讀取失敗: {files[0]}: {e}", file=sys.stderr)

    if not frames:
        raise ValueError(f"{run_dir} 找不到 aligned_metrics.csv 或 focus/bg client csv")

    df = pd.concat(frames, axis=1).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.replace([np.inf, -np.inf], np.nan)

    for c in df.columns:
        if c.endswith("_req_count"):
            df[c] = df[c].fillna(0)

    df = df.interpolate(method="time", limit_direction="both")
    df = df.ffill().bfill()

    df = df.dropna(axis=1, how="all")
    nunique = df.nunique(dropna=True)
    df = df.loc[:, nunique > 1]

    return df


def select_targets(df, max_targets=18):
    cols = list(df.columns)
    selected = []

    for key in PREFERRED_TARGET_KEYWORDS:
        for c in cols:
            if key in c and c not in selected:
                selected.append(c)

    if len(selected) < 3:
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        for c in numeric_cols:
            if c not in selected:
                selected.append(c)
            if len(selected) >= max_targets:
                break

    return selected[:max_targets]


def make_supervised(df, target_cols, horizon, lags, feature_cols=None):
    num = df.select_dtypes(include=[np.number]).copy()

    for c in target_cols:
        if c not in num.columns:
            num[c] = np.nan

    base_cols = [c for c in num.columns if num[c].notna().mean() > 0.8]

    if len(base_cols) > 80:
        priority = []
        keywords = [
            "latency", "success", "req_count",
            "DCGM", "gpu", "mem", "perf", "cpu",
            "branch", "cache", "swap"
        ]

        for c in base_cols:
            if c in target_cols or any(k.lower() in c.lower() for k in keywords):
                priority.append(c)

        base_cols = priority[:80]

    feat = {}

    for c in base_cols:
        s = num[c]

        for lag in lags:
            feat[f"{c}__lag{lag}s"] = s.shift(lag)

        feat[f"{c}__roll5_mean"] = s.rolling(5, min_periods=1).mean()
        feat[f"{c}__roll15_mean"] = s.rolling(15, min_periods=1).mean()
        feat[f"{c}__roll15_std"] = s.rolling(15, min_periods=2).std()

    X = pd.DataFrame(feat, index=num.index)
    y = num[target_cols].shift(-horizon)

    data = pd.concat([X, y.add_prefix("target__")], axis=1)
    data = data.replace([np.inf, -np.inf], np.nan).dropna()

    X = data[[c for c in data.columns if not c.startswith("target__")]]
    y = data[[f"target__{c}" for c in target_cols]]
    y.columns = target_cols

    if feature_cols is not None:
        for c in feature_cols:
            if c not in X.columns:
                X[c] = 0.0
        X = X[feature_cols]

    return X, y


def expand_run_glob(pattern):
    pattern = pattern.replace("~", str(Path.home()))
    p = Path(pattern)

    if "*" not in pattern:
        return [p] if p.exists() else []

    if pattern.startswith("/"):
        return sorted(Path("/").glob(pattern[1:]))
    else:
        return sorted(Path(".").glob(pattern))


def train(args):
    if XGBRegressor is None:
        raise SystemExit("尚未安裝 xgboost，請先執行：pip install xgboost")

    run_dirs = []

    if args.runs:
        run_dirs.extend([Path(p).expanduser() for p in args.runs])

    if args.run_glob:
        run_dirs.extend(expand_run_glob(args.run_glob))

    run_dirs = [p for p in run_dirs if p.exists() and p.is_dir()]

    if not run_dirs:
        raise SystemExit("沒有找到任何 run directory。請用 --runs 或 --run-glob 指定。")

    dfs = []

    for rd in run_dirs:
        df = load_run(rd)
        dfs.append(df)
        print(f"[OK] loaded {rd}: rows={len(df)}, cols={len(df.columns)}")

    all_df = pd.concat(dfs).sort_index()
    target_cols = select_targets(all_df, args.max_targets)

    print("\n[INFO] target columns:")
    for c in target_cols:
        print(" -", c)

    X_list = []
    y_list = []

    for df in dfs:
        X_i, y_i = make_supervised(df, target_cols, args.horizon, args.lags)
        if not X_i.empty:
            X_list.append(X_i)
            y_list.append(y_i)

    if not X_list:
        raise SystemExit("沒有產生有效 supervised samples。請確認 run 長度與欄位。")

    X = pd.concat(X_list)
    y = pd.concat(y_list)

    if len(X) < args.min_samples:
        raise SystemExit(
            f"有效訓練樣本太少：{len(X)} < {args.min_samples}。"
            "請增加 normal baseline duration 或 run 數。"
        )

    X_train, X_val, y_train, y_val = train_test_split(
        X, y,
        test_size=args.val_ratio,
        random_state=42,
        shuffle=True
    )

    base = XGBRegressor(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        subsample=0.85,
        colsample_bytree=0.85,
        objective="reg:squarederror",
        tree_method="hist",
        random_state=42,
        n_jobs=args.n_jobs,
    )

    model = MultiOutputRegressor(base)
    model.fit(X_train, y_train)

    pred = pd.DataFrame(model.predict(X_val), columns=target_cols, index=y_val.index)
    residual = y_val - pred

    rows = []
    thresholds = {}

    for c in target_cols:
        err = residual[c].dropna()
        abs_err = err.abs()

        mae = mean_absolute_error(y_val[c], pred[c])
        rmse = float(np.sqrt(mean_squared_error(y_val[c], pred[c])))

        try:
            r2 = r2_score(y_val[c], pred[c])
        except Exception:
            r2 = np.nan

        thr_abs_p99 = float(abs_err.quantile(0.99))
        thr_abs_mean3std = float(abs_err.mean() + 3 * abs_err.std())
        thr = max(thr_abs_p99, thr_abs_mean3std)

        thresholds[c] = thr

        rows.append({
            "target": c,
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "residual_abs_p95": float(abs_err.quantile(0.95)),
            "residual_abs_p99": thr_abs_p99,
            "threshold_abs": thr,
            "normal_value_mean": float(y_val[c].mean()),
            "normal_value_p95": float(y_val[c].quantile(0.95)),
            "normal_value_p99": float(y_val[c].quantile(0.99)),
        })

    out = Path(args.model_out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    bundle = {
        "model": model,
        "feature_cols": X.columns.tolist(),
        "target_cols": target_cols,
        "thresholds_abs": thresholds,
        "horizon": args.horizon,
        "lags": args.lags,
        "runs": [str(p) for p in run_dirs],
    }

    joblib.dump(bundle, out)

    report = pd.DataFrame(rows)
    report_path = out.with_suffix(".validation_report.csv")
    report.to_csv(report_path, index=False)

    print(f"\n[SAVED] model: {out}")
    print(f"[SAVED] validation report: {report_path}")
    print("\n===== validation summary =====")
    print(report.to_string(index=False))


def score(args):
    bundle = joblib.load(Path(args.model).expanduser())

    model = bundle["model"]
    feature_cols = bundle["feature_cols"]
    target_cols = bundle["target_cols"]
    thresholds = bundle["thresholds_abs"]
    horizon = int(bundle["horizon"])
    lags = bundle["lags"]

    run_dir = Path(args.run).expanduser()
    df = load_run(run_dir)

    X, y = make_supervised(
        df,
        target_cols,
        horizon,
        lags,
        feature_cols=feature_cols
    )

    if X.empty:
        raise SystemExit("沒有可評分樣本。請確認 run 內有足夠長度的 csv。")

    pred = pd.DataFrame(model.predict(X), columns=target_cols, index=X.index)

    result = pd.DataFrame(index=X.index)
    flag_cols = []

    for c in target_cols:
        actual = y[c]
        p = pred[c]
        resid = actual - p
        thr = float(thresholds.get(c, np.nan))

        result[f"actual__{c}"] = actual
        result[f"pred__{c}"] = p
        result[f"residual__{c}"] = resid

        lc = c.lower()

        if "success_rate" in lc:
            flag = (p - actual) > thr
        elif "latency" in lc or "temp" in lc or "used" in lc or "util" in lc:
            flag = resid > thr
        else:
            flag = resid.abs() > thr

        fc = f"flag__{c}"
        result[fc] = flag.astype(int)
        flag_cols.append(fc)

    result["anomaly_score"] = result[flag_cols].mean(axis=1)
    result["is_anomaly"] = (result["anomaly_score"] >= args.score_threshold).astype(int)

    outdir = Path(args.outdir).expanduser() if args.outdir else run_dir / "normal_behavior_score"
    outdir.mkdir(parents=True, exist_ok=True)

    result_path = outdir / "normal_forecast_score.csv"
    result.to_csv(result_path, index_label="ts")

    summary = {
        "run": str(run_dir),
        "model": str(args.model),
        "rows": int(len(result)),
        "horizon_sec": horizon,
        "score_threshold": args.score_threshold,
        "anomaly_rows": int(result["is_anomaly"].sum()),
        "anomaly_ratio": float(result["is_anomaly"].mean()),
        "top_flag_counts": result[flag_cols].sum().sort_values(ascending=False).head(20).to_dict(),
    }

    summary_path = outdir / "anomaly_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"[SAVED] score csv: {result_path}")
    print(f"[SAVED] summary: {summary_path}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(
        description="Normal behavior forecasting model using XGBoost"
    )

    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("train")
    p.add_argument("--runs", nargs="*", default=[])
    p.add_argument("--run-glob", default="")
    p.add_argument("--model-out", required=True)
    p.add_argument("--horizon", type=int, default=10)
    p.add_argument("--lags", type=int, nargs="*", default=[0, 1, 3, 5, 10, 30])
    p.add_argument("--max-targets", type=int, default=18)
    p.add_argument("--min-samples", type=int, default=300)
    p.add_argument("--val-ratio", type=float, default=0.2)
    p.add_argument("--n-estimators", type=int, default=400)
    p.add_argument("--max-depth", type=int, default=5)
    p.add_argument("--learning-rate", type=float, default=0.03)
    p.add_argument("--n-jobs", type=int, default=4)
    p.set_defaults(func=train)

    p = sub.add_parser("score")
    p.add_argument("--model", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--outdir", default="")
    p.add_argument("--score-threshold", type=float, default=0.2)
    p.set_defaults(func=score)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
