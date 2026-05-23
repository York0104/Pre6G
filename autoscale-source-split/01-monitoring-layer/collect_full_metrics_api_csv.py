#!/usr/bin/env python3
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from collect_node_metrics_csv import (
    HOME_OUTPUT_ROOT,
    append_json_snapshot,
    append_row,
    flatten_row,
    iso_now,
    safe_name,
)


API_BASE_URL = os.getenv("AUTOSCALE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
API_TOKEN = os.getenv("AUTOSCALE_API_TOKEN", "").strip()
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "30"))
OUTPUT_ROOT = Path(os.path.expanduser(os.getenv("OUTPUT_ROOT", str(HOME_OUTPUT_ROOT))))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))


def build_output_dir() -> Path:
    out_dir = OUTPUT_ROOT / time.strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw_json").mkdir(parents=True, exist_ok=True)
    return out_dir


def build_headers() -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    return headers


def fetch_full_metrics() -> Dict[str, Any]:
    req = urllib.request.Request(
        f"{API_BASE_URL}/api/v1/full-metrics",
        headers=build_headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON response: {exc}") from exc


def normalize_node(node_payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    node = {
        "node_name": node_payload.get("node_name", "unknown"),
        "node_type": node_payload.get("node_type", "unknown"),
        "aggregator": node_payload.get("aggregator", ""),
    }
    payload = node_payload.get("payload")
    if not isinstance(payload, dict):
        payload = {
            "collector_status": "error",
            "collector_error": "payload_missing_or_invalid",
        }
    return node, payload


def write_manifest(path: Path, nodes: List[Dict[str, Any]]) -> None:
    manifest = {
        "generated_at": iso_now(),
        "api_base_url": API_BASE_URL,
        "count": len(nodes),
        "nodes": nodes,
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    output_dir = build_output_dir()
    raw_json_dir = output_dir / "raw_json"
    log_path = output_dir / "collector.log"
    snapshot_path = raw_json_dir / "full_metrics_response.jsonl"

    stop = {"value": False}

    def handle_signal(_signum: int, _frame: Any) -> None:
        stop["value"] = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(f"API base: {API_BASE_URL}")
    print(f"Interval: {INTERVAL_SECONDS}s")
    print(f"Output dir: {output_dir}")

    cycle_index = 0
    seen_manifest = False

    with log_path.open("a", encoding="utf-8") as log:
        while not stop["value"]:
            cycle_index += 1
            cycle_started = time.time()
            print(f"[cycle {cycle_index}] start {iso_now(int(cycle_started))}")
            try:
                response = fetch_full_metrics()
                append_json_snapshot(snapshot_path, response)
                nodes = response.get("nodes", [])
                if not isinstance(nodes, list):
                    raise RuntimeError("response.nodes is not a list")

                normalized_nodes: List[Dict[str, Any]] = []
                for node_payload in nodes:
                    if not isinstance(node_payload, dict):
                        continue
                    node, payload = normalize_node(node_payload)
                    normalized_nodes.append(node)
                    fieldnames, row = flatten_row(payload, node)
                    csv_name = f"{safe_name(node['node_type'])}_{safe_name(node['node_name'])}.csv"
                    jsonl_name = f"{safe_name(node['node_type'])}_{safe_name(node['node_name'])}.jsonl"
                    append_row(output_dir / csv_name, fieldnames, row)
                    append_json_snapshot(raw_json_dir / jsonl_name, payload)
                    log.write(f"{iso_now()} COLLECT {node['node_name']} status={row.get('collector_status')}\n")
                    log.flush()
                    print(f"[cycle {cycle_index}] {node['node_name']}: {row.get('collector_status')}")

                if not seen_manifest:
                    write_manifest(output_dir / "nodes_manifest.json", normalized_nodes)
                    seen_manifest = True

            except Exception as exc:
                log.write(f"{iso_now()} ERROR full-metrics {exc}\n")
                log.flush()
                print(f"[cycle {cycle_index}] API error: {exc}", file=sys.stderr)

            remaining = INTERVAL_SECONDS - (time.time() - cycle_started)
            if remaining > 0 and not stop["value"]:
                print(f"[cycle {cycle_index}] sleeping {int(remaining)}s until next collection")
            while remaining > 0 and not stop["value"]:
                sleep_chunk = min(1.0, remaining)
                time.sleep(sleep_chunk)
                remaining -= sleep_chunk

        log.write(f"{iso_now()} STOP user_interrupted\n")

    print(f"Stopped. Data saved in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
