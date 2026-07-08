#!/usr/bin/env python3
import hashlib
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HOST = os.getenv("NODE_SENTINEL_HOST", "0.0.0.0").strip()
PORT = int(os.getenv("NODE_SENTINEL_PORT", "18080"))
COMPUTE_LOOPS = int(os.getenv("NODE_SENTINEL_COMPUTE_LOOPS", "8000"))
COMPUTE_MAX_MS = float(os.getenv("NODE_SENTINEL_COMPUTE_MAX_MS", "2000"))
COMPUTE_INTERVAL_SECONDS = float(os.getenv("NODE_SENTINEL_COMPUTE_INTERVAL_SECONDS", "1.0"))
RESULT_STALE_MS = float(os.getenv("NODE_SENTINEL_RESULT_STALE_MS", "3000"))
STATUS_MEMINFO = Path(os.getenv("NODE_SENTINEL_MEMINFO", "/proc/meminfo"))
STATUS_LOADAVG = Path(os.getenv("NODE_SENTINEL_LOADAVG", "/proc/loadavg"))

STATE_LOCK = threading.Lock()
WORKER_STATE = {
    "generation": 0,
    "running": False,
    "last_started_ts": None,
    "last_finished_ts": None,
    "last_success_ts": None,
    "last_compute_ms": None,
    "last_ok": False,
    "last_error": "",
    "loops": COMPUTE_LOOPS,
    "digest_prefix": "",
}


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def monotonic_ms() -> float:
    return time.monotonic() * 1000.0


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


def snapshot_state():
    with STATE_LOCK:
        return dict(WORKER_STATE)


def compute_result_payload():
    state = snapshot_state()
    now_ms = monotonic_ms()
    age_ms = None
    if state["last_success_ts"] is not None:
        age_ms = round(now_ms - state["last_success_ts"], 3)
    ok = bool(state["last_ok"])
    if age_ms is None or age_ms > RESULT_STALE_MS:
        ok = False
    return {
        "ok": ok,
        "worker_running": state["running"],
        "generation": state["generation"],
        "loops": state["loops"],
        "last_compute_ms": state["last_compute_ms"],
        "last_error": state["last_error"],
        "last_success_ts": state["last_success_ts"],
        "last_finished_ts": state["last_finished_ts"],
        "age_ms": age_ms,
        "result_stale_ms": RESULT_STALE_MS,
        "digest_prefix": state["digest_prefix"],
    }


def compute_worker():
    while True:
        with STATE_LOCK:
            WORKER_STATE["running"] = True
            WORKER_STATE["generation"] += 1
            WORKER_STATE["last_started_ts"] = monotonic_ms()
        try:
            result = run_compute_check()
            finished_ts = monotonic_ms()
            with STATE_LOCK:
                WORKER_STATE["running"] = False
                WORKER_STATE["last_finished_ts"] = finished_ts
                WORKER_STATE["last_compute_ms"] = result["elapsed_ms"]
                WORKER_STATE["last_ok"] = bool(result["ok"])
                WORKER_STATE["loops"] = result["loops"]
                WORKER_STATE["digest_prefix"] = result["digest_prefix"]
                if result["ok"]:
                    WORKER_STATE["last_success_ts"] = finished_ts
                    WORKER_STATE["last_error"] = ""
                else:
                    WORKER_STATE["last_error"] = "compute_too_slow"
        except Exception as exc:
            finished_ts = monotonic_ms()
            with STATE_LOCK:
                WORKER_STATE["running"] = False
                WORKER_STATE["last_finished_ts"] = finished_ts
                WORKER_STATE["last_ok"] = False
                WORKER_STATE["last_error"] = str(exc)
        time.sleep(COMPUTE_INTERVAL_SECONDS)


def log_event(payload: dict):
    print(json.dumps(payload, ensure_ascii=True), flush=True)


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
        started = time.perf_counter()
        response_code = 200
        if self.path == "/healthz":
            self._write_json(200, {
                "ok": True,
                "service": "node-sentinel",
                "hostname": socket.gethostname(),
                "timestamp": iso_now(),
                "pid": os.getpid(),
                "thread_id": threading.get_ident(),
            })
        elif self.path == "/compute-check":
            result = compute_result_payload()
            response_code = 200 if result["ok"] else 503
            self._write_json(response_code, {
                "ok": result["ok"],
                "hostname": socket.gethostname(),
                "timestamp": iso_now(),
                "compute_check": result,
            })
        elif self.path == "/status":
            self._write_json(200, {
                "ok": True,
                "hostname": socket.gethostname(),
                "timestamp": iso_now(),
                "load_average": read_loadavg(),
                "mem_available_bytes": read_mem_available_bytes(),
                "compute_worker": compute_result_payload(),
            })
        else:
            response_code = 404
            self._write_json(404, {
                "ok": False,
                "error": "not_found",
                "path": self.path,
                "timestamp": iso_now(),
            })
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        log_event({
            "event": "http_request",
            "endpoint": self.path,
            "method": "GET",
            "status_code": response_code,
            "elapsed_ms": elapsed_ms,
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "timestamp": iso_now(),
        })


def main():
    worker = threading.Thread(target=compute_worker, name="compute-worker", daemon=True)
    worker.start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log_event(
        {
            "event": "node_sentinel_start",
            "host": HOST,
            "port": PORT,
            "compute_loops": COMPUTE_LOOPS,
            "compute_max_ms": COMPUTE_MAX_MS,
            "compute_interval_seconds": COMPUTE_INTERVAL_SECONDS,
            "result_stale_ms": RESULT_STALE_MS,
            "pid": os.getpid(),
        }
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
