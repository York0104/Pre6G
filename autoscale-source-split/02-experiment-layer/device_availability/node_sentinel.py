#!/usr/bin/env python3
import hashlib
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HOST = os.getenv("NODE_SENTINEL_HOST", "0.0.0.0").strip()
PORT = int(os.getenv("NODE_SENTINEL_PORT", "18080"))
COMPUTE_LOOPS = int(os.getenv("NODE_SENTINEL_COMPUTE_LOOPS", "20000"))
COMPUTE_MAX_MS = float(os.getenv("NODE_SENTINEL_COMPUTE_MAX_MS", "2000"))
STATUS_MEMINFO = Path(os.getenv("NODE_SENTINEL_MEMINFO", "/proc/meminfo"))
STATUS_LOADAVG = Path(os.getenv("NODE_SENTINEL_LOADAVG", "/proc/loadavg"))


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_mem_available_bytes():
    try:
        with STATUS_MEMINFO.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except OSError:
        return None
    return None


def read_loadavg():
    try:
        text = STATUS_LOADAVG.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    parts = text.split()
    if len(parts) < 3:
        return None
    try:
        return {
            "load1": float(parts[0]),
            "load5": float(parts[1]),
            "load15": float(parts[2]),
        }
    except ValueError:
        return None


def run_compute_check():
    start = time.perf_counter()
    digest = b"node-sentinel"
    for i in range(COMPUTE_LOOPS):
        digest = hashlib.sha256(digest + str(i).encode("ascii")).digest()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return {
        "ok": elapsed_ms < COMPUTE_MAX_MS,
        "elapsed_ms": round(elapsed_ms, 3),
        "loops": COMPUTE_LOOPS,
        "digest_prefix": digest.hex()[:16],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "node-sentinel/0.1"

    def log_message(self, fmt, *args):
        return

    def _write_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self._write_json(200, {
                "ok": True,
                "service": "node-sentinel",
                "hostname": socket.gethostname(),
                "timestamp": iso_now(),
            })
            return

        if self.path == "/compute-check":
            result = run_compute_check()
            self._write_json(200 if result["ok"] else 503, {
                "ok": result["ok"],
                "hostname": socket.gethostname(),
                "timestamp": iso_now(),
                "compute_check": result,
            })
            return

        if self.path == "/status":
            self._write_json(200, {
                "ok": True,
                "hostname": socket.gethostname(),
                "timestamp": iso_now(),
                "load_average": read_loadavg(),
                "mem_available_bytes": read_mem_available_bytes(),
            })
            return

        self._write_json(404, {
            "ok": False,
            "error": "not_found",
            "path": self.path,
            "timestamp": iso_now(),
        })


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        json.dumps(
            {
                "event": "node_sentinel_start",
                "host": HOST,
                "port": PORT,
                "compute_loops": COMPUTE_LOOPS,
                "compute_max_ms": COMPUTE_MAX_MS,
            },
            ensure_ascii=True,
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
