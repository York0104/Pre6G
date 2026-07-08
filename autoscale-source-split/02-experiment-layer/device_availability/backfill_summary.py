#!/usr/bin/env python3
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_rows(csv_path: Path):
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build_summary(rows: list[dict], sample_interval: float, target_node: str):
    total = len(rows)
    down = sum(1 for row in rows if row["state"] == "DOWN")
    degraded = sum(1 for row in rows if row["state"] == "DEGRADED")
    transient = sum(1 for row in rows if int(row.get("is_transient_anomaly", "0")) == 1)
    functional_impairment = sum(
        1 for row in rows if row.get("sample_reason", "") in {"compute_check_failed", "compute_check_timeout"}
    )
    total_obs = total * sample_interval
    down_seconds = down * sample_interval
    availability = 100.0 if total == 0 else ((total - down) / total) * 100.0
    reason_counts = {}
    confirmed_outage_events = 0
    prev_state = "UP"
    for row in rows:
        reason = row.get("downtime_reason", "")
        if not reason:
            prev_state = row["state"]
            continue
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if row["state"] == "DOWN" and prev_state != "DOWN":
            confirmed_outage_events += 1
        prev_state = row["state"]
    return {
        "target_node": target_node,
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
        "generated_by": "backfill_summary.py",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--summary-out", default="")
    ap.add_argument("--sample-interval-seconds", type=float, default=5.0)
    ap.add_argument("--target-node", default="")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    rows = load_rows(csv_path)
    if not rows:
        raise SystemExit("availability.csv has no data rows")

    target_node = args.target_node or rows[0].get("node", "unknown")
    payload = build_summary(rows, args.sample_interval_seconds, target_node)
    summary_path = Path(args.summary_out) if args.summary_out else csv_path.with_name("summary.json")
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[INFO] wrote summary to {summary_path}")


if __name__ == "__main__":
    main()
