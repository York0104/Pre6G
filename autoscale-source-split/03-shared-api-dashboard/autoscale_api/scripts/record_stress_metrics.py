#!/usr/bin/env python3
# /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/autoscale_api/scripts/record_stress_metrics.py
import sys
import os
import json
import time
import signal
from pathlib import Path
from datetime import datetime

print("[DEBUG] record_stress_metrics.py start")

current_dir = os.path.dirname(os.path.abspath(__file__))
api_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(api_dir)
split_root = os.path.dirname(project_root)
monitoring_dir = os.path.join(split_root, "01-monitoring-layer")

print("[DEBUG] current_dir =", current_dir)
print("[DEBUG] api_dir =", api_dir)
print("[DEBUG] project_root =", project_root)
print("[DEBUG] monitoring_dir =", monitoring_dir)

if project_root not in sys.path:
    sys.path.append(project_root)
if os.path.isdir(monitoring_dir) and monitoring_dir not in sys.path:
    sys.path.append(monitoring_dir)

VM_AGGREGATOR_MODULE = os.getenv("VM_AGGREGATOR_MODULE", "vm_aggregator")

print(f"[DEBUG] importing {VM_AGGREGATOR_MODULE} ...")
vm_mod = __import__(VM_AGGREGATOR_MODULE, fromlist=["collect_state_for_node"])
collect_state_for_node = vm_mod.collect_state_for_node
print(f"[DEBUG] import {VM_AGGREGATOR_MODULE} ok")

RUNNING = True


def handle_stop(signum, frame):
    global RUNNING
    RUNNING = False


signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)


NODE = (os.getenv("NODE") or os.uname().nodename).strip()
K8S_NODE = (os.getenv("K8S_NODE") or NODE).strip()
NODE_EXPORTER_INSTANCE = os.getenv("NODE_EXPORTER_INSTANCE", "").strip()
NAMESPACE = os.getenv("NAMESPACE", "intent-lab").strip()

INTERVAL_SEC = float(os.getenv("INTERVAL_SEC", "2"))
STATE_FILE = Path(os.getenv("STATE_FILE", "/tmp/stress_phase_state.json"))
OUT_DIR = Path(os.getenv("OUT_DIR", "./data/stress_runs"))
RUN_TAG = os.getenv("RUN_TAG", datetime.now().strftime("%Y%m%d_%H%M%S"))
OUT_FILE = OUT_DIR / f"stress_metrics_{RUN_TAG}.jsonl"
LATEST_FILE = OUT_DIR / "stress_metrics_latest.json"


def load_phase_state():
    if not STATE_FILE.exists():
        return {
            "phase_name": "unknown",
            "load_percent": None,
            "cpu_load_percent": None,
            "memory_size_percent": None,
        }

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "phase_name": data.get("phase_name", "unknown"),
            "load_percent": data.get("load_percent"),
            "cpu_load_percent": data.get("cpu_load_percent"),
            "memory_size_percent": data.get("memory_size_percent"),
        }
    except Exception as e:
        return {
            "phase_name": "state_read_error",
            "load_percent": None,
            "cpu_load_percent": None,
            "memory_size_percent": None,
            "error": str(e),
        }


def build_snapshot():
    raw = collect_state_for_node(
        node_name=NODE,
        namespace=NAMESPACE,
        k8s_node_name=K8S_NODE,
    )
    phase = load_phase_state()

    snapshot = {
        "sample_ts": int(time.time()),
        "sample_time": datetime.now().isoformat(timespec="seconds"),
        "observer_node": NODE,
        "k8s_node": K8S_NODE,
        "namespace": NAMESPACE,
        "stress_phase": phase,
        "metrics": raw,
    }
    return snapshot


def append_jsonl(path: Path, obj: dict):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def write_latest(path: Path, obj: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    meta = {
        "run_tag": RUN_TAG,
        "node": NODE,
        "k8s_node": K8S_NODE,
        "node_exporter_instance": NODE_EXPORTER_INSTANCE or None,
        "namespace": NAMESPACE,
        "interval_sec": INTERVAL_SEC,
        "state_file": str(STATE_FILE),
        "output_jsonl": str(OUT_FILE),
    }

    print(json.dumps({"event": "start", **meta}, ensure_ascii=False))

    while RUNNING:
        t0 = time.time()
        try:
            snapshot = build_snapshot()
            append_jsonl(OUT_FILE, snapshot)
            write_latest(LATEST_FILE, snapshot)
            print(json.dumps({
                "event": "sampled",
                "time": snapshot["sample_time"],
                "phase": snapshot["stress_phase"].get("phase_name"),
                "load_percent": snapshot["stress_phase"].get("load_percent")
            }, ensure_ascii=False))
        except Exception as e:
            err = {
                "sample_ts": int(time.time()),
                "sample_time": datetime.now().isoformat(timespec="seconds"),
                "observer_node": NODE,
                "k8s_node": K8S_NODE,
                "namespace": NAMESPACE,
                "stress_phase": load_phase_state(),
                "error": str(e),
            }
            append_jsonl(OUT_FILE, err)
            write_latest(LATEST_FILE, err)
            print(json.dumps({"event": "error", "error": str(e)}, ensure_ascii=False))

        elapsed = time.time() - t0
        sleep_time = max(0.0, INTERVAL_SEC - elapsed)
        time.sleep(sleep_time)

    print(json.dumps({"event": "stop", "run_tag": RUN_TAG}, ensure_ascii=False))


if __name__ == "__main__":
    main()
