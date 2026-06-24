#!/usr/bin/env python3
import csv
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent
HOME_OUTPUT_ROOT = Path.home() / "node_metric_csv_logs"
INTERVAL_SECONDS = 60
DEFAULT_NAMESPACE = "intent-lab"
EXTRA_NODES_CONFIG = ROOT / "collector_nodes.json"


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

TEXT_PATH_COLUMNS = [
    "cluster_semantic.gpu.mode",
    "target_node_semantic.gpu.mode",
    "target_node_semantic.gpu_pressure.status",
    "target_node_semantic.namespace_total_instant_local.status",
]


def iso_now(ts: Optional[int] = None) -> str:
    if ts is None:
        ts = int(time.time())
    return datetime.fromtimestamp(ts).isoformat()


def safe_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in name)


def expand_env_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: expand_env_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_values(v) for v in value]
    if isinstance(value, str):
        return os.path.expanduser(os.path.expandvars(value))
    return value


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
    return {
        "ts": ts_value,
        "datetime": iso_now(int(ts_value)),
        "node_name": node["node_name"],
        "node_type": node["node_type"],
        "aggregator": node["aggregator"],
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
    for path in TEXT_PATH_COLUMNS:
        value = get_path(payload, path, None)
        if value is not None:
            row[path] = value
    fieldnames = COMMON_COLUMNS + sorted(k for k in row.keys() if k not in COMMON_COLUMNS)
    return fieldnames, row


def load_nodes() -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    payload: Dict[str, Any]
    nodes_json = ROOT / "nodes.json"

    if nodes_json.exists():
        with nodes_json.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        proc = subprocess.run(
            ["kubectl", "get", "nodes", "-o", "json"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "kubectl get nodes failed")
        payload = json.loads(proc.stdout)

    for item in payload.get("items", []):
        metadata = item.get("metadata", {})
        name = metadata.get("name")
        if not name:
            continue
        nodes.append({
            "node_name": name,
            "node_type": "k8s",
            "aggregator": "vm_aggregator.py",
            "env": {
                "NODE": name,
                "K8S_NODE": name,
                "NAMESPACE": DEFAULT_NAMESPACE,
            },
        })
    if EXTRA_NODES_CONFIG.exists():
        with EXTRA_NODES_CONFIG.open("r", encoding="utf-8") as fh:
            extra_payload = json.load(fh)
        for item in extra_payload.get("extra_nodes", []):
            nodes.append(expand_env_values(item))
    return nodes


def build_output_dir() -> Path:
    out_dir = HOME_OUTPUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw_json").mkdir(parents=True, exist_ok=True)
    return out_dir


def run_aggregator(node: Dict[str, Any]) -> Dict[str, Any]:
    env = os.environ.copy()
    env.update(node.get("env", {}))
    script = ROOT / node["aggregator"]
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=50,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"{node['aggregator']} failed")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON output: {exc}") from exc


def write_manifest(path: Path, nodes: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["node_name", "node_type", "aggregator", "availability"])
        writer.writeheader()
        for node in nodes:
            writer.writerow({
                "node_name": node["node_name"],
                "node_type": node["node_type"],
                "aggregator": node["aggregator"],
                "availability": node.get("availability", ""),
            })


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


def build_error_row(node: Dict[str, Any], message: str) -> Tuple[List[str], Dict[str, Any]]:
    payload = {"collector_status": "error", "collector_error": message}
    return flatten_row(payload, node)


def discover_available_nodes(nodes: List[Dict[str, Any]], log_path: Path) -> List[Dict[str, Any]]:
    available: List[Dict[str, Any]] = []
    with log_path.open("a", encoding="utf-8") as log:
        for node in nodes:
            print(f"[probe] {node['node_name']} ({node['node_type']}) via {node['aggregator']}")
            try:
                payload = run_aggregator(node)
                if payload.get("collector_status") == "ok":
                    node["availability"] = "ok"
                    available.append(node)
                    log.write(f"{iso_now()} AVAILABLE {node['node_name']} via {node['aggregator']}\n")
                    print(f"[ok]    {node['node_name']} available")
                else:
                    node["availability"] = f"error:{payload.get('collector_error') or payload.get('error', '')}"
                    log.write(f"{iso_now()} SKIP {node['node_name']} {node['availability']}\n")
                    print(f"[skip]  {node['node_name']} {node['availability']}")
            except Exception as exc:
                node["availability"] = f"error:{exc}"
                log.write(f"{iso_now()} SKIP {node['node_name']} error:{exc}\n")
                print(f"[skip]  {node['node_name']} error:{exc}")
            log.flush()
    return available


def main() -> int:
    output_dir = build_output_dir()
    log_path = output_dir / "collector.log"
    nodes = load_nodes()
    print(f"Session output: {output_dir}")
    print(f"Loaded {len(nodes)} candidate nodes. Probing availability...")
    available = discover_available_nodes(nodes, log_path)
    write_manifest(output_dir / "nodes_manifest.csv", nodes)

    if not available:
        print(f"No available nodes found. See {log_path}", file=sys.stderr)
        return 1

    stop = {"value": False}

    def handle_signal(_signum: int, _frame: Any) -> None:
        stop["value"] = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(f"Available nodes: {len(available)}")
    for node in available:
        print(f"  - {node['node_name']} ({node['node_type']})")
    print(f"Writing CSV files to {output_dir}")
    cycle_index = 0
    raw_json_dir = output_dir / "raw_json"
    with log_path.open("a", encoding="utf-8") as log:
        while not stop["value"]:
            cycle_index += 1
            cycle_started = time.time()
            print(f"[cycle {cycle_index}] start {iso_now(int(cycle_started))}")
            for node in available:
                payload: Dict[str, Any]
                try:
                    payload = run_aggregator(node)
                    fieldnames, row = flatten_row(payload, node)
                except Exception as exc:
                    payload = {"collector_status": "error", "collector_error": str(exc)}
                    fieldnames, row = flatten_row(payload, node)
                csv_name = f"{safe_name(node['node_type'])}_{safe_name(node['node_name'])}.csv"
                append_row(output_dir / csv_name, fieldnames, row)
                jsonl_name = f"{safe_name(node['node_type'])}_{safe_name(node['node_name'])}.jsonl"
                append_json_snapshot(raw_json_dir / jsonl_name, payload)
                log.write(f"{iso_now()} COLLECT {node['node_name']} status={row.get('collector_status')}\n")
                log.flush()
                print(f"[cycle {cycle_index}] {node['node_name']}: {row.get('collector_status')}")

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
