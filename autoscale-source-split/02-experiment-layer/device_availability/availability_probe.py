#!/usr/bin/env python3
import argparse
import csv
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def http_get(url: str, timeout: float):
    started = time.perf_counter()
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return resp.status, body.decode("utf-8", errors="replace"), elapsed_ms


def probe_json(url: str, timeout: float):
    try:
        code, payload_text, elapsed_ms = http_get(url, timeout)
        payload = json.loads(payload_text)
        return {
            "ok": code == 200,
            "http_code": code,
            "elapsed_ms": round(elapsed_ms, 3),
            "payload": payload,
            "error": "",
        }
    except urllib.error.HTTPError as exc:
        elapsed_ms = 0.0
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""
        return {
            "ok": False,
            "http_code": exc.code,
            "elapsed_ms": elapsed_ms,
            "payload": {"raw": body[:200]},
            "error": f"http_error:{exc.code}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "http_code": 0,
            "elapsed_ms": 0.0,
            "payload": "",
            "error": str(exc),
        }


def probe_text(url: str, timeout: float):
    try:
        code, payload_text, elapsed_ms = http_get(url, timeout)
        return {
            "ok": code == 200,
            "http_code": code,
            "elapsed_ms": round(elapsed_ms, 3),
            "payload_preview": payload_text[:200],
            "error": "",
        }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "http_code": exc.code,
            "elapsed_ms": 0.0,
            "payload_preview": "",
            "error": f"http_error:{exc.code}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "http_code": 0,
            "elapsed_ms": 0.0,
            "payload_preview": "",
            "error": str(exc),
        }


def kubectl_node_ready(node_name: str):
    cmd = [
        "kubectl",
        "get",
        "node",
        node_name,
        "-o",
        "jsonpath={range .status.conditions[*]}{.type}={.status}{\"\\n\"}{end}",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        return False, f"kubectl_error:{exc.stderr.strip() or exc.stdout.strip()}"

    mapping = {}
    for line in proc.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        mapping[key.strip()] = value.strip()
    return mapping.get("Ready") == "True", ""


def load_phase_name(phase_file: Path):
    if not phase_file.exists():
        return "unknown"
    try:
        data = json.loads(phase_file.read_text(encoding="utf-8"))
    except Exception:
        return "state_read_error"
    return str(data.get("phase_name", "unknown"))


def classify_sample(ready_ok, health, compute, compute_latency_ms, compute_timeout_ms, degraded_threshold_ms):
    if not ready_ok:
        return "DOWN", "node_not_ready"
    if not health["ok"]:
        return "DEGRADED", "sentinel_unreachable"
    if not compute["ok"]:
        return "DEGRADED", "compute_check_failed"
    if compute_latency_ms >= compute_timeout_ms:
        return "DEGRADED", "compute_check_timeout"
    if compute_latency_ms >= degraded_threshold_ms:
        return "DEGRADED", "compute_latency_high"
    return "UP", ""


def classify_effective_state(
    sample_state,
    sample_reason,
    health_failure_streak,
    health_failure_confirmation_count,
):
    if sample_reason == "node_not_ready":
        return "DOWN", sample_reason, False
    if sample_reason == "sentinel_unreachable":
        if health_failure_streak >= health_failure_confirmation_count:
            return "DOWN", "sentinel_confirmed_outage", False
        return "DEGRADED", sample_reason, True
    if sample_state == "DEGRADED":
        return "DEGRADED", sample_reason, False
    return "UP", "", False


def append_row(csv_path: Path, fieldnames, row: dict):
    exists = csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def write_summary(out_dir: Path, rows: list, sample_interval: float, target: str):
    total = len(rows)
    down = sum(1 for row in rows if row["state"] == "DOWN")
    degraded = sum(1 for row in rows if row["state"] == "DEGRADED")
    transient = sum(1 for row in rows if int(row["is_transient_anomaly"]) == 1)
    functional_impairment = sum(1 for row in rows if row["sample_reason"] in {"compute_check_failed", "compute_check_timeout"})
    total_obs = total * sample_interval
    down_seconds = down * sample_interval
    availability = 100.0 if total == 0 else ((total - down) / total) * 100.0
    reason_counts = {}
    confirmed_outage_events = 0
    prev_state = "UP"
    for row in rows:
        reason = row["downtime_reason"]
        if not reason:
            prev_state = row["state"]
            continue
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if row["state"] == "DOWN" and prev_state != "DOWN":
            confirmed_outage_events += 1
        prev_state = row["state"]
    payload = {
        "target_node": target,
        "sampling_interval_seconds": sample_interval,
        "samples_total": total,
        "samples_down": down,
        "samples_degraded": degraded,
        "samples_transient_anomaly": transient,
        "samples_functional_impairment": functional_impairment,
        "confirmed_outage_events": confirmed_outage_events,
        "total_observation_seconds": total_obs,
        "total_down_seconds": down_seconds,
        "availability_percent": round(availability, 6),
        "downtime_reason_breakdown": reason_counts,
        "generated_at": iso_now(),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-node", default="icclz1")
    ap.add_argument("--target-host", default="140.113.179.6")
    ap.add_argument("--sentinel-port", type=int, default=18080)
    ap.add_argument("--metrics-url", default="http://140.113.179.6:9100/metrics")
    ap.add_argument("--interval-seconds", type=float, default=5.0)
    ap.add_argument("--iterations", type=int, default=0)
    ap.add_argument("--http-timeout-seconds", type=float, default=2.5)
    ap.add_argument("--compute-timeout-ms", type=float, default=2000.0)
    ap.add_argument("--degraded-threshold-ms", type=float, default=1000.0)
    ap.add_argument("--health-failure-confirmation-count", type=int, default=3)
    ap.add_argument("--phase-file", default="results/current_phase.json")
    ap.add_argument("--out-dir", default="results/manual_run")
    ap.add_argument("--stop-phase-name", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "availability.csv"
    log_path = out_dir / "probe.log"
    phase_file = Path(args.phase_file)

    fieldnames = [
        "timestamp",
        "phase",
        "node",
        "ready",
        "healthz_ok",
        "compute_ok",
        "metrics_ok",
        "healthz_ms",
        "compute_ms",
        "health_failure_streak",
        "compute_failure_streak",
        "sample_reason",
        "anomaly_reason",
        "is_transient_anomaly",
        "state",
        "downtime_reason",
    ]
    rows = []
    sentinel_base = f"http://{args.target_host}:{args.sentinel_port}"
    health_failure_streak = 0
    compute_failure_streak = 0

    remaining = args.iterations
    while True:
        ts = iso_now()
        phase = load_phase_name(phase_file)
        ready_ok, ready_error = kubectl_node_ready(args.target_node)
        health = probe_json(f"{sentinel_base}/healthz", args.http_timeout_seconds)
        compute = probe_json(f"{sentinel_base}/compute-check", args.http_timeout_seconds)
        metrics = probe_text(args.metrics_url, args.http_timeout_seconds)

        compute_latency_ms = compute["elapsed_ms"]
        sample_state, sample_reason = classify_sample(
            ready_ok,
            health,
            compute,
            compute_latency_ms,
            args.compute_timeout_ms,
            args.degraded_threshold_ms,
        )
        health_failure_streak = 0 if health["ok"] else health_failure_streak + 1
        compute_failure = sample_reason in {"compute_check_failed", "compute_check_timeout"}
        compute_failure_streak = 0 if not compute_failure else compute_failure_streak + 1
        state, reason, is_transient_anomaly = classify_effective_state(
            sample_state,
            sample_reason,
            health_failure_streak,
            args.health_failure_confirmation_count,
        )
        if state == "UP" and ready_error:
            reason = ready_error
        anomaly_reason = sample_reason if state != "DOWN" else ""

        row = {
            "timestamp": ts,
            "phase": phase,
            "node": args.target_node,
            "ready": int(ready_ok),
            "healthz_ok": int(health["ok"]),
            "compute_ok": int(compute["ok"]),
            "metrics_ok": int(metrics["ok"]),
            "healthz_ms": f"{health['elapsed_ms']:.3f}",
            "compute_ms": f"{compute_latency_ms:.3f}",
            "health_failure_streak": health_failure_streak,
            "compute_failure_streak": compute_failure_streak,
            "sample_reason": sample_reason,
            "anomaly_reason": anomaly_reason,
            "is_transient_anomaly": int(is_transient_anomaly),
            "state": state,
            "downtime_reason": reason,
        }
        append_row(csv_path, fieldnames, row)
        rows.append(row)

        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "timestamp": ts,
                "phase": phase,
                "ready_ok": ready_ok,
                "ready_error": ready_error,
                "health": health,
                "compute": compute,
                "metrics": {
                    "ok": metrics["ok"],
                    "http_code": metrics["http_code"],
                    "error": metrics["error"],
                },
                "health_failure_streak": health_failure_streak,
                "compute_failure_streak": compute_failure_streak,
                "sample_state": sample_state,
                "sample_reason": sample_reason,
                "anomaly_reason": anomaly_reason,
                "is_transient_anomaly": is_transient_anomaly,
                "state": state,
                "downtime_reason": reason,
            }, ensure_ascii=False) + "\n")

        if remaining > 0:
            remaining -= 1
        if remaining == 0 and args.iterations > 0:
            break
        if args.stop_phase_name and phase == args.stop_phase_name:
            break
        time.sleep(args.interval_seconds)

    write_summary(out_dir, rows, args.interval_seconds, args.target_node)


if __name__ == "__main__":
    main()
