#!/usr/bin/env python3
import csv
import json
import os
import signal
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

COMMON_COLUMNS = [
    "ts",
    "datetime",
    "node_name",
    "node_type",
    "aggregator",
    "collector_status",
    "collector_error",
    "schema",
]

API_BASE_URL = os.getenv("AUTOSCALE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
API_TOKEN = os.getenv("AUTOSCALE_API_TOKEN", "").strip()
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "30"))
OUTPUT_ROOT = Path(
    os.path.expanduser(
        os.getenv("OUTPUT_ROOT", str(Path.home() / "node_metric_csv_logs"))
    )
)
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))


def iso_now(ts: Optional[int] = None) -> str:
    if ts is None:
        ts = int(time.time())
    return datetime.fromtimestamp(ts).isoformat()


def safe_name(name: str) -> str:
    return "".join(
        ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(name)
    )


def get_path(payload: Dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = payload
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def collect_numeric_metrics(value: Any, prefix: str = "") -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}

    if isinstance(value, dict):
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            metrics.update(collect_numeric_metrics(child, next_prefix))
        return metrics

    if isinstance(value, list):
        for idx, child in enumerate(value):
            next_prefix = f"{prefix}[{idx}]"
            metrics.update(collect_numeric_metrics(child, next_prefix))
        return metrics

    if isinstance(value, bool):
        metrics[prefix] = int(value)
        return metrics

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        metrics[prefix] = value
        return metrics

    return metrics


def base_row(payload: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
    ts_value = (
        get_path(payload, "meta.ts", None)
        or get_path(payload, "meta.timestamp", None)
        or int(time.time())
    )

    try:
        ts_int = int(ts_value)
    except Exception:
        ts_int = int(time.time())

    return {
        "ts": ts_int,
        "datetime": iso_now(ts_int),
        "node_name": node.get("node_name", "unknown"),
        "node_type": node.get("node_type", "unknown"),
        "aggregator": node.get("aggregator", ""),
        "collector_status": payload.get("collector_status", ""),
        "collector_error": payload.get("collector_error", payload.get("error", "")),
        "schema": payload.get("schema", ""),
    }


def flatten_row(payload: Dict[str, Any], node: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
    row = base_row(payload, node)
    numeric_metrics = collect_numeric_metrics(payload)

    for key in COMMON_COLUMNS:
        numeric_metrics.pop(key, None)

    for key in list(numeric_metrics.keys()):
        if key.startswith("meta."):
            numeric_metrics.pop(key, None)

    row.update(numeric_metrics)
    fieldnames = COMMON_COLUMNS + sorted(
        key for key in row.keys() if key not in COMMON_COLUMNS
    )
    return fieldnames, row


def read_existing_rows(csv_path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    if not csv_path.exists():
        return [], []

    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def merge_fieldnames(existing: List[str], new: List[str]) -> List[str]:
    merged = list(existing)

    for field in new:
        if field not in merged:
            merged.append(field)

    for field in COMMON_COLUMNS:
        if field in merged:
            merged.remove(field)

    return COMMON_COLUMNS + sorted(merged)


def rewrite_csv(csv_path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            normalized = {key: row.get(key, "") for key in fieldnames}
            writer.writerow(normalized)


def append_row(csv_path: Path, fieldnames: List[str], row: Dict[str, Any]) -> None:
    existing_fields, existing_rows = read_existing_rows(csv_path)

    if not existing_fields:
        rewrite_csv(csv_path, fieldnames, [row])
        return

    merged_fields = merge_fieldnames(existing_fields, fieldnames)
    normalized_row = {key: row.get(key, "") for key in merged_fields}

    if merged_fields != existing_fields:
        existing_rows.append(normalized_row)
        rewrite_csv(csv_path, merged_fields, existing_rows)
        return

    with csv_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=existing_fields)
        writer.writerow(normalized_row)


def append_json_snapshot(jsonl_path: Path, payload: Dict[str, Any]) -> None:
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False))
        fh.write("\n")


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
            "schema": "",
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

    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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

                    csv_name = (
                        f"{safe_name(node['node_type'])}_{safe_name(node['node_name'])}.csv"
                    )
                    jsonl_name = (
                        f"{safe_name(node['node_type'])}_{safe_name(node['node_name'])}.jsonl"
                    )

                    append_row(output_dir / csv_name, fieldnames, row)
                    append_json_snapshot(raw_json_dir / jsonl_name, payload)

                    log.write(
                        f"{iso_now()} COLLECT {node['node_name']} "
                        f"status={row.get('collector_status')}\n"
                    )
                    log.flush()

                    print(
                        f"[cycle {cycle_index}] {node['node_name']}: "
                        f"{row.get('collector_status')}"
                    )

                if not seen_manifest:
                    write_manifest(output_dir / "nodes_manifest.json", normalized_nodes)
                    seen_manifest = True

            except Exception as exc:
                log.write(f"{iso_now()} ERROR full-metrics {exc}\n")
                log.flush()
                print(f"[cycle {cycle_index}] API error: {exc}")

            remaining = INTERVAL_SECONDS - (time.time() - cycle_started)
            if remaining > 0 and not stop["value"]:
                print(
                    f"[cycle {cycle_index}] sleeping {int(remaining)}s until next collection"
                )

            while remaining > 0 and not stop["value"]:
                chunk = min(1.0, remaining)
                time.sleep(chunk)
                remaining -= chunk

        log.write(f"{iso_now()} STOP user_interrupted\n")

    print(f"Stopped. Data saved in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
