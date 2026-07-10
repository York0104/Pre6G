#!/usr/bin/env python3
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def load_csv(path: Path):
    with path.open() as fh:
        return list(csv.DictReader(fh))


def parse_summary(path: Path):
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def scan_lines(path: Path, patterns):
    if not path.exists():
        return []
    lines = []
    for line in path.read_text(errors="replace").splitlines():
        if any(p.search(line) for p in patterns):
            lines.append(line)
    return lines


def extract_pod_states(path: Path):
    states = Counter()
    by_pod = defaultdict(Counter)
    if not path.exists():
        return states, by_pod
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        pod, status = parts[0], parts[2]
        if not pod.startswith("device-avail-r2-"):
            continue
        by_pod[pod][status] += 1
        states[status] += 1
    return states, by_pod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result-dir", required=True)
    args = ap.parse_args()

    base = Path(args.result_dir)
    rows = load_csv(base / "availability.csv")
    summary = parse_summary(base / "summary.json")
    pod_states, pod_by_name = extract_pod_states(base / "pod_watch.log")
    event_hits = scan_lines(
        base / "k8s_events_watch.log",
        [
            re.compile(r"\bEvicted\b"),
            re.compile(r"\bOOMKilled\b"),
            re.compile(r"\bMemoryPressure\b"),
            re.compile(r"\bnode-pressure\b", re.I),
            re.compile(r"\bErrImagePull\b"),
            re.compile(r"\bImagePullBackOff\b"),
        ],
    )
    node_hits = scan_lines(
        base / "node_watch.log",
        [re.compile(r"NotReady"), re.compile(r"MemoryPressure", re.I)],
    )

    phase_counts = {}
    for phase in ["BASELINE", "MEM-AGG-M", "RECOVERY-1", "MEM-AGG-H", "RECOVERY-2", "MIX-AGG-M", "FINAL-RECOVERY"]:
        subset = [r for r in rows if r["phase"] == phase]
        if not subset:
            continue
        phase_counts[phase] = {
            "samples": len(subset),
            "states": dict(Counter(r["state"] for r in subset)),
            "reasons": dict(Counter(r["downtime_reason"] for r in subset if r["downtime_reason"])),
        }

    payload = {
        "samples_total": len(rows),
        "summary": summary,
        "phase_counts": phase_counts,
        "pod_state_counts": dict(pod_states),
        "oomkilled_pods": sorted([name for name, counts in pod_by_name.items() if counts.get("OOMKilled", 0) > 0]),
        "evicted_pods": sorted([name for name, counts in pod_by_name.items() if counts.get("Evicted", 0) > 0]),
        "errimagepull_pods": sorted([name for name, counts in pod_by_name.items() if counts.get("ErrImagePull", 0) > 0]),
        "event_hits": event_hits[:200],
        "node_hits": node_hits[:50],
        "eviction_effective": bool(event_hits and any("Evicted" in line or "MemoryPressure" in line for line in event_hits)),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
