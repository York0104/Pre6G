#!/usr/bin/env python3
"""Open-loop YOLO request generator with fixed scheduled arrivals.

This client separates offered workload demand from realized throughput.  It
uses a monotonic clock schedule, bounded in-flight requests, and explicit
records for dropped/missed launches when the client cannot keep up.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import math
import os
import random
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ISO_FMT = "%Y-%m-%dT%H:%M:%S.%f%z"


@dataclass(frozen=True)
class RateSegment:
    name: str
    start_s: float
    end_s: float
    target_rps: float


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime(ISO_FMT)


def iso_from_epoch(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).strftime(ISO_FMT)


def load_rate_profile(args: argparse.Namespace) -> List[RateSegment]:
    if args.rate_profile_json:
        with open(args.rate_profile_json, "r", encoding="utf-8") as f:
            raw = json.load(f)
        segments = raw.get("segments", raw if isinstance(raw, list) else [])
        profile = []
        for i, item in enumerate(segments):
            profile.append(
                RateSegment(
                    name=str(item.get("name", f"segment_{i}")),
                    start_s=float(item["start_s"]),
                    end_s=float(item["end_s"]),
                    target_rps=float(item["target_rps"]),
                )
            )
        return profile
    return [RateSegment(name="constant", start_s=0.0, end_s=float(args.duration_s), target_rps=float(args.target_rps))]


def load_images(args: argparse.Namespace) -> List[str]:
    images: List[str] = []
    if args.image_list:
        with open(args.image_list, "r", encoding="utf-8") as f:
            images.extend([line.strip() for line in f if line.strip()])
    if args.image:
        images.extend(args.image)
    if not images:
        raise SystemExit("at least one --image or --image-list entry is required")
    return images


def build_schedule(duration_s: float, segments: Iterable[RateSegment]) -> List[Dict[str, Any]]:
    """Build fixed arrival schedule without depending on response completion."""
    rows: List[Dict[str, Any]] = []
    idx = 0
    for seg in sorted(segments, key=lambda x: x.start_s):
        start = max(0.0, seg.start_s)
        end = min(duration_s, seg.end_s)
        if end <= start or seg.target_rps <= 0:
            continue
        interval = 1.0 / seg.target_rps
        t = start
        while t < end - 1e-9:
            rows.append(
                {
                    "schedule_index": idx,
                    "scheduled_elapsed_s": round(t, 9),
                    "target_rps": seg.target_rps,
                    "profile_name": seg.name,
                }
            )
            idx += 1
            t += interval
    rows.sort(key=lambda r: (r["scheduled_elapsed_s"], r["schedule_index"]))
    for i, row in enumerate(rows):
        row["schedule_index"] = i
    return rows


def quantile(values: List[float], q: float) -> Optional[float]:
    clean = sorted(v for v in values if v is not None and not math.isnan(v))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pos = (len(clean) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return clean[int(pos)]
    return clean[lo] + (clean[hi] - clean[lo]) * (pos - lo)


def _is_success(row: Dict[str, Any]) -> bool:
    return str(row.get("success")).lower() == "true"


def _is_completed(row: Dict[str, Any]) -> bool:
    return bool(row.get("complete_time_iso"))


def aggregate_arrival_binned_rows(
    rows: List[Dict[str, Any]],
    bucket_s: int = 1,
    duration_s: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Bucket by scheduled arrival time for offered-load accounting."""
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        elapsed = row.get("scheduled_elapsed_s")
        if elapsed is None or elapsed == "":
            continue
        b = int(float(elapsed) // bucket_s)
        buckets.setdefault(b, []).append(row)

    out: List[Dict[str, Any]] = []
    if duration_s is not None:
        bucket_ids = list(range(0, int(math.ceil(duration_s / bucket_s))))
    else:
        bucket_ids = sorted(buckets)
    for b in bucket_ids:
        part = buckets.get(b, [])
        launched = [r for r in part if r.get("launch_status") == "launched"]
        dropped = [r for r in part if r.get("launch_status") == "dropped_max_inflight"]
        completed = [r for r in launched if _is_completed(r)]
        successes = [r for r in completed if _is_success(r)]
        timeouts = [r for r in part if r.get("error_type") == "timeout"]
        failures = [r for r in part if str(r.get("success")).lower() == "false"]
        lats = [float(r["e2e_latency_ms"]) for r in successes if r.get("e2e_latency_ms") not in (None, "")]
        misses = [
            r
            for r in part
            if r.get("launch_status") == "dropped_max_inflight"
            or float(r.get("schedule_delay_ms") or 0.0) > bucket_s * 1000
        ]
        out.append(
            {
                "elapsed_s": b * bucket_s,
                "bin_type": "scheduled_arrival",
                "latency_quantile_basis": "successful completions whose scheduled arrival falls in this bin",
                "offered_rps": len(part) / float(bucket_s),
                "scheduled_request_count": len(part),
                "launched_request_count": len(launched),
                "dropped_max_inflight_count": len(dropped),
                "arrival_bin_completed_count": len(completed),
                "arrival_bin_successful_completion_count": len(successes),
                "arrival_bin_completion_fraction": len(completed) / len(launched) if launched else 0.0,
                "arrival_bin_success_fraction": len(successes) / len(completed) if completed else 0.0,
                "fail_rate": len(failures) / len(part) if part else 0.0,
                "timeout_rate": len(timeouts) / len(part) if part else 0.0,
                "inflight_count_max": max((int(r.get("inflight_at_schedule") or 0) for r in part), default=0),
                "client_backlog_or_schedule_miss": len(misses),
                "latency_p50": quantile(lats, 0.50),
                "latency_p95": quantile(lats, 0.95),
                "latency_p99": quantile(lats, 0.99),
            }
        )
    return out


def aggregate_completion_binned_rows(rows: List[Dict[str, Any]], bucket_s: int = 1) -> List[Dict[str, Any]]:
    """Bucket by completion time for realized service activity."""
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        elapsed = row.get("complete_elapsed_s")
        if elapsed is None or elapsed == "":
            continue
        b = int(float(elapsed) // bucket_s)
        buckets.setdefault(b, []).append(row)

    out: List[Dict[str, Any]] = []
    for b in sorted(buckets):
        part = buckets[b]
        successes = [r for r in part if _is_success(r)]
        timeouts = [r for r in part if r.get("error_type") == "timeout"]
        failures = [r for r in part if str(r.get("success")).lower() == "false"]
        lats = [float(r["e2e_latency_ms"]) for r in successes if r.get("e2e_latency_ms") not in (None, "")]
        out.append(
            {
                "elapsed_s": b * bucket_s,
                "bin_type": "completion",
                "latency_quantile_basis": "successful completions whose completion time falls in this bin",
                "realized_completed_rps": len(part) / float(bucket_s),
                "completed_request_count": len(part),
                "successful_completion_count": len(successes),
                "failed_completion_count": len(failures),
                "timeout_completion_count": len(timeouts),
                "completion_success_fraction": len(successes) / len(part) if part else 0.0,
                "completion_timeout_fraction": len(timeouts) / len(part) if part else 0.0,
                "latency_p50": quantile(lats, 0.50),
                "latency_p95": quantile(lats, 0.95),
                "latency_p99": quantile(lats, 0.99),
            }
        )
    return out


def aggregate_rows(rows: List[Dict[str, Any]], bucket_s: int = 1) -> List[Dict[str, Any]]:
    return aggregate_arrival_binned_rows(rows, bucket_s=bucket_s)


def classify_url_error(exc: urllib.error.URLError) -> str:
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    if "timed out" in str(reason).lower() or "timeout" in str(reason).lower():
        return "timeout"
    return "url_error"


def parse_server_json(body: bytes) -> Dict[str, Any]:
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def extract_server_latency(data: Dict[str, Any]) -> Dict[str, Any]:
    keys = {
        "server_latency_ms": ["latency_ms", "server_latency_ms", "inference_latency_ms"],
        "server_total_latency_ms": ["total_latency_ms", "server_total_latency_ms"],
        "server_time": ["server_time", "timestamp"],
        "server_pod_name": ["pod_name", "pod"],
        "server_node_name": ["node_name", "node"],
        "server_service_role": ["service_role", "role"],
        "num_boxes": ["num_boxes", "detections"],
        "model": ["model"],
        "device": ["device"],
        "imgsz": ["imgsz", "image_size"],
        "filename": ["filename", "image"],
    }
    out: Dict[str, Any] = {}
    for dest, choices in keys.items():
        out[dest] = next((data.get(k) for k in choices if k in data), "")
    return out


def post_image(url: str, image_path: str, timeout_s: float) -> Dict[str, Any]:
    boundary = "----pre6g-openloop-boundary"
    name = os.path.basename(image_path)
    with open(image_path, "rb") as f:
        payload = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = resp.read()
        return {"status_code": resp.status, "body": data}


def run_one_request(base: Dict[str, Any], url: str, image_path: str, timeout_s: float) -> Dict[str, Any]:
    row = dict(base)
    send_perf = time.monotonic()
    send_epoch = time.time()
    row["send_time_iso"] = iso_from_epoch(send_epoch)
    row["schedule_delay_ms"] = max(0.0, (send_perf - float(base["scheduled_monotonic_s"])) * 1000.0)
    try:
        resp = post_image(url, image_path, timeout_s)
        complete_perf = time.monotonic()
        row["complete_time_iso"] = iso_from_epoch(time.time())
        row["complete_elapsed_s"] = complete_perf - float(base["client_start_monotonic_s"])
        row["e2e_latency_ms"] = (complete_perf - send_perf) * 1000.0
        row["status_code"] = resp["status_code"]
        row["success"] = 200 <= int(resp["status_code"]) < 300
        row["error_type"] = "" if row["success"] else "http_error"
        row["error_msg"] = ""
        row.update(extract_server_latency(parse_server_json(resp["body"])))
    except (TimeoutError, socket.timeout) as exc:
        complete_perf = time.monotonic()
        row["complete_time_iso"] = iso_from_epoch(time.time())
        row["complete_elapsed_s"] = complete_perf - float(base["client_start_monotonic_s"])
        row["e2e_latency_ms"] = (complete_perf - send_perf) * 1000.0
        row["status_code"] = ""
        row["success"] = False
        row["error_type"] = "timeout"
        row["error_msg"] = str(exc)
    except urllib.error.URLError as exc:
        complete_perf = time.monotonic()
        row["complete_time_iso"] = iso_from_epoch(time.time())
        row["complete_elapsed_s"] = complete_perf - float(base["client_start_monotonic_s"])
        row["e2e_latency_ms"] = (complete_perf - send_perf) * 1000.0
        row["status_code"] = ""
        row["success"] = False
        row["error_type"] = classify_url_error(exc)
        row["error_msg"] = str(exc.reason)
    except Exception as exc:
        complete_perf = time.monotonic()
        row["complete_time_iso"] = iso_from_epoch(time.time())
        row["complete_elapsed_s"] = complete_perf - float(base["client_start_monotonic_s"])
        row["e2e_latency_ms"] = (complete_perf - send_perf) * 1000.0
        row["status_code"] = ""
        row["success"] = False
        row["error_type"] = type(exc).__name__
        row["error_msg"] = str(exc)
    return row


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: List[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_client(args: argparse.Namespace) -> Dict[str, Any]:
    rng = random.Random(args.seed)
    images = load_images(args)
    missing = [p for p in images if not Path(p).exists()]
    if missing and not args.dry_run:
        raise SystemExit(f"missing image files: {missing[:3]}")
    segments = load_rate_profile(args)
    schedule = build_schedule(float(args.duration_s), segments)
    start_perf = time.monotonic()
    start_epoch = time.time()
    rows: List[Dict[str, Any]] = []
    futures: Dict[concurrent.futures.Future, str] = {}

    manifest = {
        "client_type": "open_loop_request_generator",
        "created_at_utc": utc_now_iso(),
        "url": args.url,
        "duration_s": args.duration_s,
        "max_inflight": args.max_inflight,
        "timeout_s": args.timeout_s,
        "seed": args.seed,
        "dry_run": args.dry_run,
        "image_count": len(images),
        "images": images,
        "rate_segments": [seg.__dict__ for seg in segments],
        "scheduled_request_count": len(schedule),
        "definition": {
            "offered_rps": "scheduled arrivals per second",
            "arrival_binned_summary": "bucketed by scheduled arrival time; use for offered-load accounting",
            "completion_binned_summary": "bucketed by completion time; use for realized service activity",
            "realized_completed_rps": "completed responses per second by completion time; not a pure external workload signal",
        },
    }

    if args.preflight_only:
        return {"manifest": manifest, "rows": [], "arrival_summary": [], "completion_summary": []}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.max_inflight)) as pool:
        for item in schedule:
            while True:
                done = [f for f in futures if f.done()]
                for f in done:
                    rows.append(f.result())
                    futures.pop(f)
                scheduled_perf = start_perf + float(item["scheduled_elapsed_s"])
                now = time.monotonic()
                if now >= scheduled_perf:
                    break
                time.sleep(min(0.01, scheduled_perf - now))

            scheduled_epoch = start_epoch + float(item["scheduled_elapsed_s"])
            image_path = rng.choice(images)
            base = {
                "client_role": "open_loop",
                "req_id": f"ol-{item['schedule_index']:08d}",
                "schedule_index": item["schedule_index"],
                "scheduled_elapsed_s": item["scheduled_elapsed_s"],
                "scheduled_monotonic_s": scheduled_perf,
                "client_start_monotonic_s": start_perf,
                "scheduled_time_iso": iso_from_epoch(scheduled_epoch),
                "target_url": args.url,
                "image_path": image_path,
                "image_seed": args.seed,
                "target_rps": item["target_rps"],
                "profile_name": item["profile_name"],
                "inflight_at_schedule": len(futures),
            }
            if args.dry_run:
                row = dict(base)
                row.update({"launch_status": "dry_run", "success": "", "error_type": "", "error_msg": ""})
                rows.append(row)
                continue
            if len(futures) >= args.max_inflight:
                row = dict(base)
                row.update(
                    {
                        "launch_status": "dropped_max_inflight",
                        "send_time_iso": "",
                        "complete_time_iso": "",
                        "complete_elapsed_s": "",
                        "schedule_delay_ms": "",
                        "e2e_latency_ms": "",
                        "status_code": "",
                        "success": False,
                        "error_type": "max_inflight",
                        "error_msg": "request was scheduled but not launched because max_inflight was reached",
                    }
                )
                rows.append(row)
                continue
            base["launch_status"] = "launched"
            futures[pool.submit(run_one_request, base, args.url, image_path, args.timeout_s)] = base["req_id"]

        for f in concurrent.futures.as_completed(list(futures)):
            rows.append(f.result())

    rows.sort(key=lambda r: int(r.get("schedule_index", 0)))
    arrival_summary = aggregate_arrival_binned_rows(rows, duration_s=float(args.duration_s))
    completion_summary = aggregate_completion_binned_rows(rows)
    return {"manifest": manifest, "rows": rows, "arrival_summary": arrival_summary, "completion_summary": completion_summary}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--image", action="append")
    p.add_argument("--image-list")
    p.add_argument("--duration-s", type=float, default=60.0)
    p.add_argument("--target-rps", type=float, default=1.0)
    p.add_argument("--rate-profile-json")
    p.add_argument("--max-inflight", type=int, default=8)
    p.add_argument("--timeout-s", type=float, default=10.0)
    p.add_argument("--seed", type=int, default=20260702)
    p.add_argument("--output", required=True)
    p.add_argument("--summary-output", required=True, help="arrival-binned offered-load summary CSV")
    p.add_argument("--completion-summary-output", help="completion-binned realized service activity summary CSV")
    p.add_argument("--manifest-output", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--preflight-only", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    result = run_client(args)
    write_csv(Path(args.output), result["rows"])
    write_csv(Path(args.summary_output), result["arrival_summary"])
    completion_summary_output = args.completion_summary_output
    if not completion_summary_output:
        summary_path = Path(args.summary_output)
        completion_summary_output = str(summary_path.with_name(summary_path.stem + ".completion_binned" + summary_path.suffix))
    write_csv(Path(completion_summary_output), result["completion_summary"])
    Path(args.manifest_output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.manifest_output, "w", encoding="utf-8") as f:
        json.dump(result["manifest"], f, indent=2, ensure_ascii=False)
    print(
        json.dumps(
            {
                "rows": len(result["rows"]),
                "arrival_summary_rows": len(result["arrival_summary"]),
                "completion_summary_rows": len(result["completion_summary"]),
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
