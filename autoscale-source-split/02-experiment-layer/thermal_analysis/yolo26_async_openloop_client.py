#!/usr/bin/env python3
import argparse
import asyncio
import csv
import json
import math
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def extract_server_latency_ms(data):
    if not isinstance(data, dict):
        return math.nan

    for key in ("server_latency_ms", "latency_ms", "inference_ms", "infer_ms", "processing_ms"):
        if key in data:
            try:
                return float(data[key])
            except Exception:
                pass

    for value in data.values():
        if isinstance(value, dict):
            nested = extract_server_latency_ms(value)
            if not math.isnan(nested):
                return nested

    return math.nan


def build_multipart_request(url, image_path, image_bytes):
    parsed = urlparse(url)
    if parsed.scheme != "http":
        raise ValueError("Only http:// URLs are supported by this stdlib async client")
    if not parsed.hostname:
        raise ValueError(f"Invalid URL: {url}")

    host = parsed.hostname
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    boundary = f"----yolo26async{int(time.time() * 1000000)}"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{image_path.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode(),
        image_bytes,
        f"\r\n--{boundary}--\r\n".encode(),
    ])

    request = b"".join([
        f"POST {path} HTTP/1.1\r\n".encode(),
        f"Host: {host}:{port}\r\n".encode(),
        f"Content-Type: multipart/form-data; boundary={boundary}\r\n".encode(),
        f"Content-Length: {len(body)}\r\n".encode(),
        b"Connection: close\r\n",
        b"\r\n",
        body,
    ])

    return host, port, request


async def read_http_response(reader):
    header_bytes = await reader.readuntil(b"\r\n\r\n")
    header_text = header_bytes.decode("iso-8859-1", errors="replace")
    lines = header_text.split("\r\n")
    status_code = 0
    if lines:
        parts = lines[0].split()
        if len(parts) >= 2:
            try:
                status_code = int(parts[1])
            except Exception:
                status_code = 0

    headers = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    body = b""
    content_length = headers.get("content-length")
    if content_length is not None:
        try:
            body = await reader.readexactly(int(content_length))
        except asyncio.IncompleteReadError as exc:
            body = exc.partial
    else:
        chunks = []
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
        body = b"".join(chunks)

    return status_code, body


async def post_once(host, port, request_bytes, connect_timeout, read_timeout):
    reader = writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=connect_timeout,
        )
        writer.write(request_bytes)
        await writer.drain()
        status_code, body = await asyncio.wait_for(
            read_http_response(reader),
            timeout=read_timeout,
        )
        return status_code, body, ""
    except Exception as exc:
        return 0, b"", f"{type(exc).__name__}: {exc}"
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def run_open_loop(args):
    image_path = Path(args.image)
    if not image_path.exists():
        raise FileNotFoundError(f"image not found: {image_path}")

    host, port, request_bytes = build_multipart_request(
        args.url,
        image_path,
        image_path.read_bytes(),
    )

    semaphore = asyncio.Semaphore(args.concurrency)
    started_at_mono = time.perf_counter()
    started_at_wall = time.time()
    total_requests = int(args.seconds * args.rate_rps)
    results = []

    async def one_request(req_id, scheduled_mono):
        await asyncio.sleep(max(0.0, scheduled_mono - time.perf_counter()))

        queued_at = time.perf_counter()
        async with semaphore:
            start_mono = time.perf_counter()
            start_wall = started_at_wall + (start_mono - started_at_mono)
            status_code, body, error_msg = await post_once(
                host,
                port,
                request_bytes,
                args.connect_timeout,
                args.read_timeout,
            )
            end_mono = time.perf_counter()

        latency_ms_client = (end_mono - start_mono) * 1000.0
        queue_delay_ms = (start_mono - queued_at) * 1000.0
        schedule_lag_ms = (start_mono - scheduled_mono) * 1000.0
        success = 1 if 200 <= status_code < 300 else 0
        server_latency_ms = math.nan

        if body:
            try:
                server_latency_ms = extract_server_latency_ms(json.loads(body.decode("utf-8")))
            except Exception as exc:
                if not error_msg:
                    error_msg = f"json_parse_error: {type(exc).__name__}: {exc}"

        return {
            "client_ts": datetime.fromtimestamp(start_wall).isoformat(timespec="milliseconds"),
            "req_id": req_id,
            "scheduled_offset_sec": round(scheduled_mono - started_at_mono, 6),
            "schedule_lag_ms": round(schedule_lag_ms, 3),
            "queue_delay_ms": round(queue_delay_ms, 3),
            "latency_ms_client": round(latency_ms_client, 3),
            "status_code": status_code,
            "success": success,
            "server_latency_ms": round(server_latency_ms, 3) if not math.isnan(server_latency_ms) else "",
            "error_msg": error_msg,
        }

    tasks = []
    for i in range(total_requests):
        scheduled_mono = started_at_mono + (i / args.rate_rps)
        tasks.append(asyncio.create_task(one_request(i + 1, scheduled_mono)))

    for task in asyncio.as_completed(tasks):
        results.append(await task)

    results.sort(key=lambda row: row["req_id"])
    return results


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "client_ts",
        "req_id",
        "scheduled_offset_sec",
        "schedule_lag_ms",
        "queue_delay_ms",
        "latency_ms_client",
        "status_code",
        "success",
        "server_latency_ms",
        "error_msg",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--rate-rps", type=float, required=True)
    parser.add_argument("--csv", "--out", dest="csv", required=True)
    parser.add_argument("--concurrency", type=int, default=200)
    parser.add_argument("--connect-timeout", type=float, default=2.0)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    args = parser.parse_args()

    rows = asyncio.run(run_open_loop(args))
    write_csv(args.csv, rows)

    total = len(rows)
    success = sum(1 for row in rows if row["success"] == 1)
    failures = total - success
    achieved = success / args.seconds if args.seconds > 0 else 0.0
    attempted = total / args.seconds if args.seconds > 0 else 0.0
    print(
        f"attempted_rps={attempted:.6f} successful_rps={achieved:.6f} "
        f"total={total} success={success} failures={failures}"
    )


if __name__ == "__main__":
    main()
