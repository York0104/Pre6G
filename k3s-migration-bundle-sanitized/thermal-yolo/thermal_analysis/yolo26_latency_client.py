#!/usr/bin/env python3
import argparse
import csv
import time
from datetime import datetime
from pathlib import Path

import requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="e.g. http://100.105.48.97:30026/infer")
    ap.add_argument("--image", required=True, help="fixed input image path")
    ap.add_argument("--out", required=True, help="latency csv output")
    ap.add_argument("--seconds", type=int, required=True)
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "client_ts",
        "req_id",
        "latency_ms_client",
        "status_code",
        "success",
        "server_time",
        "server_latency_ms",
        "num_boxes",
        "error_msg",
    ]

    start = time.time()
    req_id = 0

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        while time.time() - start < args.seconds:
            req_id += 1
            row = {
                "client_ts": datetime.now().isoformat(timespec="milliseconds"),
                "req_id": req_id,
                "latency_ms_client": "",
                "status_code": "",
                "success": False,
                "server_time": "",
                "server_latency_ms": "",
                "num_boxes": "",
                "error_msg": "",
            }

            t0 = time.perf_counter()
            try:
                with open(Path(args.image).expanduser(), "rb") as imgf:
                    resp = requests.post(
                        args.url,
                        files={"file": (Path(args.image).name, imgf, "image/png")},
                        timeout=30,
                    )
                t1 = time.perf_counter()

                row["latency_ms_client"] = round((t1 - t0) * 1000.0, 3)
                row["status_code"] = resp.status_code

                if resp.ok:
                    data = resp.json()
                    row["success"] = bool(data.get("ok", False))
                    row["server_time"] = data.get("server_time", "")
                    row["server_latency_ms"] = data.get("server_latency_ms", "")
                    row["num_boxes"] = data.get("num_boxes", "")
                else:
                    row["error_msg"] = resp.text[:500]

            except Exception as e:
                t1 = time.perf_counter()
                row["latency_ms_client"] = round((t1 - t0) * 1000.0, 3)
                row["error_msg"] = str(e)

            writer.writerow(row)
            f.flush()
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
