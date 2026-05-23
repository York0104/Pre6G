#!/usr/bin/env python3
import argparse
import csv
import json
import signal
import time
from datetime import datetime, timezone

import requests


stop_requested = False


def handle_stop(signum, frame):
    global stop_requested
    stop_requested = True


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def classify_error(exc):
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "connect_timeout"
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection_error"
    if isinstance(exc, requests.exceptions.HTTPError):
        return "http_error"
    return exc.__class__.__name__


def send_one_request(session, url, image_path, timeout_sec, req_id, role):
    ts_start = now_iso()
    t0 = time.perf_counter()

    row = {
        "client_role": role,
        "req_id": req_id,
        "target_url": url,
        "client_ts_start": ts_start,
        "client_ts_end": "",
        "e2e_latency_ms": "",
        "status_code": "",
        "success": 0,
        "server_latency_ms": "",
        "server_total_latency_ms": "",
        "server_time": "",
        "server_pod_name": "",
        "server_node_name": "",
        "server_service_role": "",
        "num_boxes": "",
        "model": "",
        "device": "",
        "imgsz": "",
        "filename": "",
        "inter_request_gap_ms": "",
        "loop_elapsed_ms": "",
        "error_type": "",
        "error_msg": "",
    }

    try:
        with open(image_path, "rb") as f:
            files = {"file": (image_path.split("/")[-1], f, "image/png")}
            resp = session.post(
                url,
                files=files,
                timeout=timeout_sec,
                headers={"Connection": "close"},
            )

        t1 = time.perf_counter()
        row["client_ts_end"] = now_iso()
        row["e2e_latency_ms"] = round((t1 - t0) * 1000.0, 3)
        row["status_code"] = resp.status_code

        if resp.status_code >= 400:
            row["error_type"] = f"http_{resp.status_code}"
            row["error_msg"] = resp.text[:300]
            return row

        try:
            data = resp.json()
        except json.JSONDecodeError:
            row["error_type"] = "json_parse_error"
            row["error_msg"] = resp.text[:300]
            return row

        row["success"] = 1 if data.get("ok", False) else 0
        row["server_latency_ms"] = data.get("server_latency_ms", "")
        row["server_total_latency_ms"] = data.get("server_total_latency_ms", "")
        row["server_time"] = data.get("server_time", "")
        row["server_pod_name"] = data.get("pod_name", "")
        row["server_node_name"] = data.get("node_name", "")
        row["server_service_role"] = data.get("service_role", "")
        row["num_boxes"] = data.get("num_boxes", "")
        row["model"] = data.get("model", "")
        row["device"] = data.get("device", "")
        row["imgsz"] = data.get("imgsz", "")
        row["filename"] = data.get("filename", "")

        if row["success"] == 1:
            row["error_type"] = "normal_success"
        else:
            row["error_type"] = "server_returned_not_ok"
            row["error_msg"] = str(data)[:300]

        return row

    except Exception as exc:
        t1 = time.perf_counter()
        row["client_ts_end"] = now_iso()
        row["e2e_latency_ms"] = round((t1 - t0) * 1000.0, 3)
        row["error_type"] = classify_error(exc)
        row["error_msg"] = str(exc)[:300]
        return row


def main():
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    parser = argparse.ArgumentParser(
        description="Closed-loop serial request client for YOLO service experiments."
    )
    parser.add_argument("--role", default="measurement")
    parser.add_argument("--url", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--duration", type=float, default=1800.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fieldnames = [
        "client_role",
        "req_id",
        "target_url",
        "client_ts_start",
        "client_ts_end",
        "e2e_latency_ms",
        "status_code",
        "success",
        "server_latency_ms",
        "server_total_latency_ms",
        "server_time",
        "server_pod_name",
        "server_node_name",
        "server_service_role",
        "num_boxes",
        "model",
        "device",
        "imgsz",
        "filename",
        "inter_request_gap_ms",
        "loop_elapsed_ms",
        "error_type",
        "error_msg",
    ]

    print(f"[INFO] role={args.role}")
    print(f"[INFO] url={args.url}")
    print(f"[INFO] image={args.image}")
    print(f"[INFO] duration={args.duration}s")
    print(f"[INFO] timeout={args.timeout}s")
    print("[INFO] mode=closed_loop_serial")
    print(f"[INFO] output={args.output}")

    session = requests.Session()
    end_time = time.time() + args.duration
    req_id = 0
    prev_end = None

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        while time.time() < end_time and not stop_requested:
            loop_t0 = time.perf_counter()
            row = send_one_request(
                session=session,
                url=args.url,
                image_path=args.image,
                timeout_sec=args.timeout,
                req_id=req_id,
                role=args.role,
            )

            now_perf = time.perf_counter()
            if prev_end is not None:
                row["inter_request_gap_ms"] = round((loop_t0 - prev_end) * 1000.0, 3)
            else:
                row["inter_request_gap_ms"] = ""
            row["loop_elapsed_ms"] = round((now_perf - loop_t0) * 1000.0, 3)
            row["req_id"] = f"{args.role}-{req_id}"

            writer.writerow(row)
            f.flush()

            prev_end = now_perf
            req_id += 1

            if stop_requested:
                break

    print(f"[INFO] completed requests={req_id}")


if __name__ == "__main__":
    main()
