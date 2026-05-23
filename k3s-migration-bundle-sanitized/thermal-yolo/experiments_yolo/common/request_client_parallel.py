#!/usr/bin/env python3
import argparse
import csv
import json
import time
import traceback
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Lock

import requests


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def classify_error(exc):
    name = exc.__class__.__name__

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

    return name


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
        "error_type": "",
        "error_msg": "",
    }

    try:
        with open(image_path, "rb") as f:
            files = {
                "file": (image_path.split("/")[-1], f, "image/png")
            }
            resp = session.post(
                url,
                files=files,
                timeout=timeout_sec,
                headers={"Connection": "close"}
            )

        t1 = time.perf_counter()
        row["client_ts_end"] = now_iso()
        row["e2e_latency_ms"] = round((t1 - t0) * 1000.0, 3)
        row["status_code"] = resp.status_code

        if resp.status_code >= 400:
            row["success"] = 0
            row["error_type"] = f"http_{resp.status_code}"
            row["error_msg"] = resp.text[:300]
            return row

        try:
            data = resp.json()
        except json.JSONDecodeError:
            row["success"] = 0
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

        if row["success"] != 1:
            row["error_type"] = "server_returned_not_ok"
            row["error_msg"] = str(data)[:300]
        else:
            row["error_type"] = "normal_success"

        return row

    except Exception as exc:
        t1 = time.perf_counter()
        row["client_ts_end"] = now_iso()
        row["e2e_latency_ms"] = round((t1 - t0) * 1000.0, 3)
        row["success"] = 0
        row["error_type"] = classify_error(exc)
        row["error_msg"] = str(exc)[:300]
        return row


def writer_thread_like_write(writer, file_handle, lock, row):
    with lock:
        writer.writerow(row)
        file_handle.flush()


def run_background(args, writer, file_handle, lock):
    """
    background mode:
    多 worker 持續打 Service URL，盡量製造資源壓力。
    """
    stop_event = Event()
    end_time = time.time() + args.duration
    req_counter = 0
    req_counter_lock = Lock()

    def worker(worker_id):
        nonlocal req_counter
        session = requests.Session()

        while time.time() < end_time and not stop_event.is_set():
            with req_counter_lock:
                req_id = req_counter
                req_counter += 1

            row = send_one_request(
                session=session,
                url=args.url,
                image_path=args.image,
                timeout_sec=args.timeout,
                req_id=req_id,
                role=args.role,
            )
            row["req_id"] = f"{args.role}-{worker_id}-{req_id}"
            writer_thread_like_write(writer, file_handle, lock, row)

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(worker, i) for i in range(args.concurrency)]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception:
                traceback.print_exc()


def run_measurement(args, writer, file_handle, lock):
    """
    measurement mode:
    單 worker 時固定 interval 打目標 URL；
    多 worker 時改為高併發持續發送，用於量測 service 在真實流量下的體感。
    """
    if args.concurrency > 1:
        end_time = time.time() + args.duration
        req_counter = 0
        req_counter_lock = Lock()

        def worker(worker_id):
            nonlocal req_counter
            session = requests.Session()

            while time.time() < end_time:
                with req_counter_lock:
                    req_id = req_counter
                    req_counter += 1

                row = send_one_request(
                    session=session,
                    url=args.url,
                    image_path=args.image,
                    timeout_sec=args.timeout,
                    req_id=req_id,
                    role=args.role,
                )
                row["req_id"] = f"{args.role}-{worker_id}-{req_id}"
                writer_thread_like_write(writer, file_handle, lock, row)

        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [executor.submit(worker, i) for i in range(args.concurrency)]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception:
                    traceback.print_exc()
        return

    session = requests.Session()
    end_time = time.time() + args.duration
    req_id = 0

    while time.time() < end_time:
        loop_start = time.time()

        row = send_one_request(
            session=session,
            url=args.url,
            image_path=args.image,
            timeout_sec=args.timeout,
            req_id=req_id,
            role=args.role,
        )
        row["req_id"] = f"{args.role}-{req_id}"
        writer_thread_like_write(writer, file_handle, lock, row)

        req_id += 1

        elapsed = time.time() - loop_start
        sleep_time = max(0.0, args.interval - elapsed)
        time.sleep(sleep_time)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=["background", "measurement"])
    parser.add_argument("--url", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=10.0)
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
        "error_type",
        "error_msg",
    ]

    lock = Lock()

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        print(f"[INFO] role={args.role}")
        print(f"[INFO] url={args.url}")
        print(f"[INFO] image={args.image}")
        print(f"[INFO] duration={args.duration}s")
        print(f"[INFO] output={args.output}")

        if args.role == "background":
            print(f"[INFO] background concurrency={args.concurrency}")
            run_background(args, writer, f, lock)
        else:
            if args.concurrency > 1:
                print(f"[INFO] measurement concurrency={args.concurrency}")
            else:
                print(f"[INFO] measurement interval={args.interval}s")
            run_measurement(args, writer, f, lock)

        print("[INFO] done")


if __name__ == "__main__":
    main()
