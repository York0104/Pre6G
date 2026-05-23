#!/usr/bin/env python3
import argparse
import csv
import math
import time
from datetime import datetime
from pathlib import Path

import requests


def extract_server_latency_ms(data):
    if not isinstance(data, dict):
        return math.nan

    candidate_keys = [
        "server_latency_ms",
        "latency_ms",
        "inference_ms",
        "infer_ms",
        "processing_ms",
    ]

    for k in candidate_keys:
        if k in data:
            try:
                return float(data[k])
            except Exception:
                pass

    for v in data.values():
        if isinstance(v, dict):
            x = extract_server_latency_ms(v)
            if not math.isnan(x):
                return x

    return math.nan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--interval", type=float, required=True)
    parser.add_argument("--csv", "--out", dest="csv", required=True)
    parser.add_argument("--connect-timeout", type=float, default=2.0)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    args = parser.parse_args()

    image_path = Path(args.image)
    out_path = Path(args.csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not image_path.exists():
        raise FileNotFoundError(f"image not found: {image_path}")

    image_bytes = image_path.read_bytes()
    session = requests.Session()

    header = [
        "client_ts",
        "req_id",
        "latency_ms_client",
        "status_code",
        "success",
        "server_latency_ms",
        "error_msg",
    ]

    end_t = time.monotonic() + args.seconds
    next_t = time.monotonic()
    req_id = 0

    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        f.flush()

        while time.monotonic() < end_t:
            req_id += 1
            client_ts = datetime.now().isoformat(timespec="milliseconds")

            latency_ms_client = math.nan
            status_code = 0
            success = 0
            server_latency_ms = math.nan
            error_msg = ""

            t0 = time.perf_counter()

            try:
                files = {
                    "file": (
                        image_path.name,
                        image_bytes,
                        "application/octet-stream",
                    )
                }

                resp = session.post(
                    args.url,
                    files=files,
                    timeout=(args.connect_timeout, args.read_timeout),
                )

                t1 = time.perf_counter()
                latency_ms_client = (t1 - t0) * 1000.0
                status_code = resp.status_code
                success = 1 if 200 <= resp.status_code < 300 else 0

                try:
                    data = resp.json()
                    server_latency_ms = extract_server_latency_ms(data)
                except Exception as e:
                    error_msg = f"json_parse_error: {type(e).__name__}: {e}"

            except Exception as e:
                t1 = time.perf_counter()
                latency_ms_client = (t1 - t0) * 1000.0
                error_msg = f"{type(e).__name__}: {e}"

            writer.writerow({
                "client_ts": client_ts,
                "req_id": req_id,
                "latency_ms_client": round(latency_ms_client, 3) if not math.isnan(latency_ms_client) else "",
                "status_code": status_code,
                "success": success,
                "server_latency_ms": round(server_latency_ms, 3) if not math.isnan(server_latency_ms) else "",
                "error_msg": error_msg,
            })
            f.flush()

            next_t += args.interval
            sleep_s = next_t - time.monotonic()

            if sleep_s > 0:
                time.sleep(sleep_s)
            else:
                next_t = time.monotonic()


if __name__ == "__main__":
    main()
