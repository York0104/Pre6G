#!/usr/bin/env python3
"""Open-loop normal-cooling planner, preflight, and guarded normal-only executor.

Cooling-constrained campaign execution is intentionally not implemented here.
Only normal-cooling smoke/calibration can run live, and only with
--normal-only plus CONFIRM_NORMAL_SMOKE=YES.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[4]
RESULTS_ROOT = (
    ROOT
    / "autoscale-source-split/02-experiment-layer/experiments_yolo/results/"
    / "single_pod_bgload_fan_cycle"
)
DEFAULT_OUT_ROOT = RESULTS_ROOT / "openloop_load_thermal_campaign"
CLIENT_SCRIPT = ROOT / "autoscale-source-split/02-experiment-layer/experiments_yolo/common/open_loop_request_client.py"
VM_AGGREGATOR = ROOT / "autoscale-source-split/01-monitoring-layer/vm_aggregator.py"
VM_COLLECTOR = ROOT / "autoscale-source-split/02-experiment-layer/thermal_analysis/collect_vm_aggregator_csv.py"
CALIBRATION_ANALYZER = ROOT / "autoscale-source-split/02-experiment-layer/experiments_yolo/common/offline_normal_load_calibration_analysis.py"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


RAW_RUN_SENTINELS = (
    "measurement_raw.csv",
    "thermal.csv",
    "nvidia_smi_gpu_1s.csv",
    "vm_aggregator_timeseries.csv",
)


def discover_raw_run_dirs(root: Path) -> List[Path]:
    """Return existing raw RUN_ID directories, excluding analysis/planner outputs."""
    if not root.exists():
        return []
    out: List[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.endswith("_analysis") or child.name == "openloop_load_thermal_campaign":
            continue
        if any((child / sentinel).exists() for sentinel in RAW_RUN_SENTINELS):
            out.append(child)
    return out


def collect_tree_fingerprint(root: Path, raw_run_dirs: Optional[List[Path]] = None) -> Dict[str, str]:
    """Hash file metadata for pre-existing raw run directories only."""
    out: Dict[str, str] = {}
    dirs = raw_run_dirs if raw_run_dirs is not None else discover_raw_run_dirs(root)
    for raw_dir in dirs:
        if not raw_dir.exists():
            out[str(raw_dir.relative_to(root))] = "MISSING_DIR"
            continue
        for path in sorted(raw_dir.rglob("*")):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = str(path.relative_to(root))
            payload = f"{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
            out[rel] = hashlib.sha256(payload).hexdigest()
    return out


def validate_config(cfg: Dict[str, Any], strict: bool = False, live_normal: bool = False) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    for key in ("campaign_name", "endpoint", "workload_profiles", "cooling_conditions", "replicates", "safety"):
        if key not in cfg:
            errors.append(f"missing required key: {key}")
    endpoint = cfg.get("endpoint", {})
    if not endpoint.get("url"):
        errors.append("endpoint.url is required")
    elif is_operator_placeholder(endpoint.get("url")):
        (errors if live_normal else warnings).append("endpoint.url still contains an operator placeholder")
    for key, value in cfg.get("node_gpu_identity", {}).items():
        if is_operator_placeholder(value):
            (errors if live_normal else warnings).append(f"node_gpu_identity.{key} still contains an operator placeholder")
    profiles = cfg.get("workload_profiles", {})
    if not profiles:
        errors.append("at least one workload profile is required")
    for name, profile in profiles.items():
        if profile.get("target_rps") is None:
            warnings.append(f"workload profile {name} target_rps is null; calibration is required before live run")
        elif float(profile["target_rps"]) <= 0:
            errors.append(f"workload profile {name} target_rps must be positive")
        if int(profile.get("max_inflight", 0)) <= 0:
            errors.append(f"workload profile {name} max_inflight must be positive")
    conditions = cfg.get("cooling_conditions", {})
    if "normal_cooling" not in conditions:
        errors.append("cooling_conditions.normal_cooling is required as control")
    safety = cfg.get("safety", {})
    if safety.get("operator_max_gpu_temp_c") is None:
        msg = "safety.operator_max_gpu_temp_c is not set; operator must choose it from local policy before live campaign"
        (errors if strict else warnings).append(msg)
    if strict and cfg.get("allow_fan_control", False) and safety.get("restore_mode") != "GPU_DEFAULT":
        errors.append("fan-capable strict run requires safety.restore_mode == GPU_DEFAULT")
    if live_normal:
        normal = cfg.get("normal_live_smoke", {})
        for cond_name, cond in cfg.get("cooling_conditions", {}).items():
            if bool(cond.get("fan_control_allowed")):
                errors.append(
                    f"normal-only live config must not include fan-control cooling condition metadata: {cond_name}"
                )
            primary = str(cond.get("primary_control", "")).lower()
            if any(term in primary for term in ("fan", "coolercontrol", "cooling-profile", "restore_to_gpu_default")):
                errors.append(
                    f"normal-only live config must not include cooling-control primary_control metadata: {cond_name}"
                )
        if bool(cfg.get("background_workload", {}).get("enabled")):
            errors.append("normal-only live config must not enable background workload control")
        if not normal.get("payload_mix"):
            errors.append("normal_live_smoke.payload_mix is required for live normal-only execution")
        if normal.get("target_rps") is None and not cfg.get("calibration", {}).get("candidate_offered_rps"):
            errors.append("normal_live_smoke.target_rps or calibration.candidate_offered_rps is required")
        if normal.get("duration_s") is None and cfg.get("calibration", {}).get("duration_s") is None:
            errors.append("normal_live_smoke.duration_s or calibration.duration_s is required")
        if int(normal.get("max_inflight", 0) or 0) <= 0 and int(cfg.get("calibration", {}).get("max_inflight", 0) or 0) <= 0:
            errors.append("normal_live_smoke.max_inflight or calibration.max_inflight must be positive")
    return errors, warnings


def is_operator_placeholder(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("operator-fill") or text.startswith("operator-confirm") or text in {"", "todo", "tbd"}


def expand_matrix(cfg: Dict[str, Any], normal_only: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    conditions = cfg.get("cooling_conditions", {})
    selected_conditions = list(conditions)
    if normal_only:
        selected_conditions = [c for c in selected_conditions if c in ("normal_cooling", "natural_high_load_normal_cooling")]
    for profile_name, profile in cfg.get("workload_profiles", {}).items():
        for cond_name in selected_conditions:
            for rep in range(1, int(cfg.get("replicates", 1)) + 1):
                rows.append(
                    {
                        "workload_profile": profile_name,
                        "cooling_condition": cond_name,
                        "replicate": rep,
                        "target_rps": profile.get("target_rps"),
                        "duration_s": profile.get("duration_s"),
                        "max_inflight": profile.get("max_inflight"),
                        "payload_mix": profile.get("payload_mix", []),
                        "condition_metadata": conditions.get(cond_name, {}),
                    }
                )
    return rows


def mode_name(args: argparse.Namespace) -> str:
    if args.dry_run:
        return "dry_run"
    if args.preflight_only:
        return "preflight_only"
    if args.run_normal_smoke:
        return "normal_only_live_smoke"
    if args.calibrate_normal:
        return "normal_cooling_calibration"
    return "run_campaign_requested_fail_closed"


def build_manifest(args: argparse.Namespace, cfg: Dict[str, Any], errors: List[str], warnings: List[str]) -> Dict[str, Any]:
    matrix = expand_matrix(cfg, args.normal_only)
    run_id = f"openloop_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    live_normal = bool(args.run_normal_smoke or args.calibrate_normal)
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "experiment_timestamp_utc": utc_now_iso(),
        "git_revision": git_revision(),
        "runner_role": "normal_cooling_planner_preflight_executor",
        "live_executor_status": "normal_only_executor_available" if live_normal else "cooling_constrained_executor_not_implemented",
        "execution_mode": mode_name(args),
        "confirm_experiment_env": os.environ.get("CONFIRM_EXPERIMENT", ""),
        "confirm_normal_smoke_env": os.environ.get("CONFIRM_NORMAL_SMOKE", ""),
        "no_fan_control_executed": True,
        "no_kubernetes_scale_restart_delete_executed": True,
        "live_execution_started": False,
        "normal_only_live_allowed": live_normal,
        "campaign_name": cfg.get("campaign_name"),
        "node_gpu_identity": cfg.get("node_gpu_identity", {}),
        "container_image": cfg.get("container_image", ""),
        "yolo_model": cfg.get("yolo_model", ""),
        "endpoint": cfg.get("endpoint", {}),
        "offered_load_profiles": cfg.get("workload_profiles", {}),
        "background_workload_configuration": cfg.get("background_workload", {}),
        "cooling_condition_metadata": cfg.get("cooling_conditions", {}),
        "safety": cfg.get("safety", {}),
        "telemetry_source_availability": cfg.get("telemetry_sources", {}),
        "telemetry_gap": cfg.get("telemetry_gap", []),
        "planned_matrix": matrix,
        "preflight": {"errors": errors, "warnings": warnings},
        "abort_reason": "",
        "cleanup": {
            "restore_target": cfg.get("safety", {}).get("restore_mode", "GPU_DEFAULT"),
            "restore_attempted": False,
            "restore_result": "not_needed_in_dry_or_preflight",
        },
        "data_contract": {
            "open_loop_client_log": "required",
            "open_loop_arrival_1s_summary": "required",
            "open_loop_completion_1s_summary": "required",
            "vm_aggregator_timeseries": "required_when_available",
            "vm_query_samples": "required_for_vm_primary_features",
            "nvidia_smi_gpu_1s": "required",
            "worker_thermal_telemetry": "required_when_available",
            "control_event_log": "required",
        },
    }


def write_execution_plan(out_dir: Path, manifest: Dict[str, Any]) -> None:
    lines = [
        "# Open-loop campaign execution plan",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- mode: `{manifest['execution_mode']}`",
        f"- runner role: `{manifest['runner_role']}`",
        f"- live executor status: `{manifest['live_executor_status']}`",
        f"- live execution started: `{manifest['live_execution_started']}`",
        f"- no fan control executed: `{manifest['no_fan_control_executed']}`",
        "",
        "## Planned matrix",
        "",
        "| workload | cooling condition | replicate | target_rps | duration_s | max_inflight |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in manifest["planned_matrix"]:
        lines.append(
            f"| {row['workload_profile']} | {row['cooling_condition']} | {row['replicate']} | "
            f"{row.get('target_rps')} | {row.get('duration_s')} | {row.get('max_inflight')} |"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Cooling-constrained `--run-campaign` fails closed because that executor is not implemented.",
            "- Normal-only smoke/calibration requires `--normal-only` and `CONFIRM_NORMAL_SMOKE=YES`.",
            "- Normal-only execution must not perform fan control, CoolerControl, cooling intervention, or Kubernetes scale/restart/delete.",
            "- Missing telemetry, control failure, service outage, or temperature safety breach must abort fail-closed.",
        ]
    )
    (out_dir / "execution_plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_abort(run_dir: Path, reason: str, detail: Dict[str, Any] | None = None) -> None:
    payload = {"ts": utc_now_iso(), "abort_reason": reason, "detail": detail or {}}
    with (run_dir / "safety_abort_record.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def resolve_payload_args(payload_mix: List[str]) -> List[str]:
    args: List[str] = []
    for item in payload_mix:
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file() and path.suffix.lower() in (".txt", ".lst"):
            args.extend(["--image-list", str(path)])
        else:
            args.extend(["--image", str(path)])
    return args


def start_vm_collector(cfg: Dict[str, Any], run_dir: Path, duration_s: int) -> subprocess.Popen | None:
    if not VM_COLLECTOR.exists() or not VM_AGGREGATOR.exists():
        return None
    telemetry = cfg.get("telemetry_runtime", {})
    cmd = [
        sys.executable,
        str(VM_COLLECTOR),
        "--aggregator",
        str(VM_AGGREGATOR),
        "--out",
        str(run_dir / "vm_aggregator_timeseries.csv"),
        "--seconds",
        str(max(1, duration_s)),
        "--interval",
        str(telemetry.get("vm_agg_interval_s", 1.0)),
        "--node",
        str(telemetry.get("node", cfg.get("node_gpu_identity", {}).get("node_name", ""))),
        "--namespace",
        str(telemetry.get("namespace", "intent-lab")),
        "--mode",
        str(telemetry.get("mode", "fast")),
        "--vm-query-samples-out",
        str(run_dir / "vm_aggregator_timeseries.vm_query_samples.jsonl"),
    ]
    for flag, key in (
        ("--vm-url", "vm_url"),
        ("--netdata-url", "netdata_url"),
        ("--netdata-child-url", "netdata_child_url"),
        ("--netdata-parent-base-url", "netdata_parent_base_url"),
        ("--node-exporter-instance", "node_exporter_instance"),
    ):
        if telemetry.get(key):
            cmd.extend([flag, str(telemetry[key])])
    log = (run_dir / "vm_aggregator_timeseries.log").open("w", encoding="utf-8")
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)


def start_nvidia_smi_monitor(cfg: Dict[str, Any], run_dir: Path) -> subprocess.Popen | None:
    telemetry = cfg.get("telemetry_runtime", {})
    nvidia_cmd = (
        "nvidia-smi "
        "--query-gpu=timestamp,index,name,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm,clocks.mem "
        "--format=csv -l 1"
    )
    ssh_alias = str(telemetry.get("nvidia_smi_ssh_alias", "") or "")
    cmd = ["ssh", ssh_alias, nvidia_cmd] if ssh_alias else nvidia_cmd.split()
    out = (run_dir / "nvidia_smi_gpu_1s.csv").open("w", encoding="utf-8")
    err = (run_dir / "nvidia_smi_gpu_1s.err").open("w", encoding="utf-8")
    try:
        return subprocess.Popen(cmd, stdout=out, stderr=err, cwd=ROOT)
    except FileNotFoundError:
        out.close()
        err.close()
        return None


def stop_process(proc: subprocess.Popen | None, timeout_s: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout_s)


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def float_cell(row: Dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        raw = str(row.get(key, "") or "").strip()
        if not raw:
            return default
        match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
        return float(match.group(0)) if match else default
    except ValueError:
        return default


def summarize_telemetry(run_dir: Path) -> Dict[str, Any]:
    vm_rows = read_csv_rows(run_dir / "vm_aggregator_timeseries.csv")
    gpu_rows = read_csv_rows(run_dir / "nvidia_smi_gpu_1s.csv")
    vm_age_cols = [
        k
        for k in (vm_rows[0].keys() if vm_rows else [])
        if re.search(r"(?:^|[._])sample_age_(?:min|p50|p95|max|max_max|maximum)[._a-z]*_s$", k)
        or re.search(r"(?:^|[._])sample_age_max_(?:min|p50|p95|max)_s$", k)
    ]
    vm_ages = [float_cell(r, k, float("nan")) for r in vm_rows for k in vm_age_cols if r.get(k) not in ("", None)]
    gpu_temp_keys = ["temperature.gpu [C]", "temperature.gpu", " temperature.gpu", " temp.gpu"]
    temps = []
    for r in gpu_rows:
        for k in gpu_temp_keys:
            if k in r and r.get(k):
                temps.append(float_cell(r, k, float("nan")))
                break
    return {
        "vm_aggregator_rows": len(vm_rows),
        "nvidia_smi_rows": len(gpu_rows),
        "vm_sample_age_max_s": max(vm_ages) if vm_ages else None,
        "gpu_temperature_max_c": max(temps) if temps else None,
        "telemetry_available": bool(vm_rows or gpu_rows),
    }


def evaluate_abort_conditions(run_dir: Path, cfg: Dict[str, Any]) -> Tuple[bool, List[str], Dict[str, Any]]:
    safety = cfg.get("safety", {})
    aborts: List[str] = []
    detail: Dict[str, Any] = {}
    telemetry = summarize_telemetry(run_dir)
    detail["telemetry"] = telemetry
    if safety.get("abort_on_missing_gpu_telemetry", True) and telemetry["nvidia_smi_rows"] == 0:
        aborts.append("missing_gpu_telemetry")
    max_temp = telemetry.get("gpu_temperature_max_c")
    if max_temp is not None and safety.get("operator_max_gpu_temp_c") is not None and float(max_temp) > float(safety["operator_max_gpu_temp_c"]):
        aborts.append("gpu_temperature_over_operator_limit")

    arrival_rows = read_csv_rows(run_dir / "open_loop_arrival_1s_summary.csv")
    if arrival_rows:
        max_drop_frac = max(
            (
                float_cell(r, "dropped_max_inflight_count")
                / max(float_cell(r, "scheduled_request_count"), 1.0)
                for r in arrival_rows
            ),
            default=0.0,
        )
        max_timeout = max((float_cell(r, "timeout_rate") for r in arrival_rows), default=0.0)
        max_fail = max((float_cell(r, "fail_rate") for r in arrival_rows), default=0.0)
        detail["client"] = {"max_drop_fraction": max_drop_frac, "max_timeout_rate": max_timeout, "max_fail_rate": max_fail}
        if max_drop_frac > float(safety.get("max_inflight_saturation_abort_fraction", 0.2)):
            aborts.append("client_max_inflight_saturation")
        if max_timeout > float(safety.get("timeout_rate_abort_fraction", 0.2)):
            aborts.append("timeout_burst")
        if max_fail > float(safety.get("error_rate_abort_fraction", 0.2)):
            aborts.append("error_burst")
    else:
        aborts.append("missing_arrival_summary")
    if not (run_dir / "open_loop_client_raw.csv").exists() or not (run_dir / "open_loop_completion_1s_summary.csv").exists():
        aborts.append("request_client_output_missing")
    return bool(aborts), aborts, detail


def run_open_loop_client(cfg: Dict[str, Any], profile: Dict[str, Any], run_dir: Path) -> int:
    payload_mix = profile.get("payload_mix") or cfg.get("normal_live_smoke", {}).get("payload_mix") or []
    cmd = [
        sys.executable,
        str(CLIENT_SCRIPT),
        "--url",
        str(cfg.get("endpoint", {}).get("url", "")),
        "--duration-s",
        str(profile["duration_s"]),
        "--target-rps",
        str(profile["target_rps"]),
        "--max-inflight",
        str(profile["max_inflight"]),
        "--timeout-s",
        str(profile.get("timeout_s", cfg.get("normal_live_smoke", {}).get("timeout_s", 10))),
        "--output",
        str(run_dir / "open_loop_client_raw.csv"),
        "--summary-output",
        str(run_dir / "open_loop_arrival_1s_summary.csv"),
        "--completion-summary-output",
        str(run_dir / "open_loop_completion_1s_summary.csv"),
        "--manifest-output",
        str(run_dir / "open_loop_client_manifest.json"),
    ] + resolve_payload_args(payload_mix)
    log = run_dir / "open_loop_client.log"
    with log.open("w", encoding="utf-8") as f:
        proc = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, text=True)
    return int(proc.returncode)


def run_normal_level(cfg: Dict[str, Any], out_root: Path, profile: Dict[str, Any], label: str) -> Tuple[Path, int]:
    run_dir = out_root / f"{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "created_at_utc": utc_now_iso(),
            "execution_mode": "normal_cooling_live_level",
            "cooling_condition": "normal_cooling",
            "no_fan_control_executed": True,
            "no_coolercontrol_executed": True,
            "no_kubernetes_scale_restart_delete_executed": True,
            "endpoint": cfg.get("endpoint", {}),
            "offered_load_profile": profile,
            "safety": cfg.get("safety", {}),
            "telemetry_runtime": cfg.get("telemetry_runtime", {}),
        },
    )
    duration_s = int(float(profile["duration_s"])) + int(cfg.get("telemetry_runtime", {}).get("tail_seconds", 5))
    vm_proc = start_vm_collector(cfg, run_dir, duration_s)
    smi_proc = start_nvidia_smi_monitor(cfg, run_dir)
    abort = {"started_at_utc": utc_now_iso(), "abort_reason": "", "completed": False}
    write_json(run_dir / "safety_abort_record.json", abort)
    rc = 1
    try:
        rc = run_open_loop_client(cfg, profile, run_dir)
        if rc != 0:
            append_abort(run_dir, "open_loop_client_failed", {"returncode": rc})
        time.sleep(float(cfg.get("telemetry_runtime", {}).get("post_client_wait_s", 1)))
    finally:
        stop_process(vm_proc)
        stop_process(smi_proc)
    should_abort, reasons, detail = evaluate_abort_conditions(run_dir, cfg)
    if should_abort:
        append_abort(run_dir, "safety_or_data_quality_abort", {"reasons": reasons, **detail})
        rc = rc or 1
    abort.update({"completed": rc == 0 and not should_abort, "finished_at_utc": utc_now_iso(), "abort_reason": ";".join(reasons) if should_abort else ""})
    write_json(run_dir / "safety_abort_record.json", abort)
    write_json(run_dir / "telemetry_availability_summary.json", detail.get("telemetry", summarize_telemetry(run_dir)))
    return run_dir, rc


def normal_smoke_profile(cfg: Dict[str, Any]) -> Dict[str, Any]:
    profile = dict(cfg.get("normal_live_smoke", {}))
    for key in ("target_rps", "duration_s", "max_inflight"):
        if profile.get(key) is None:
            raise ValueError(f"normal_live_smoke.{key} is required")
    return profile


def calibration_profiles(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    calib = cfg.get("calibration", {})
    base = cfg.get("normal_live_smoke", {})
    profiles = []
    for value in calib.get("candidate_offered_rps", []):
        profiles.append(
            {
                "target_rps": value,
                "duration_s": calib.get("duration_s", base.get("duration_s")),
                "max_inflight": calib.get("max_inflight", base.get("max_inflight")),
                "timeout_s": calib.get("timeout_s", base.get("timeout_s", 10)),
                "payload_mix": calib.get("payload_mix", base.get("payload_mix", [])),
            }
        )
    if not profiles:
        raise ValueError("calibration.candidate_offered_rps must contain at least one candidate")
    return profiles


def run_live_normal(args: argparse.Namespace, cfg: Dict[str, Any], out_dir: Path, manifest: Dict[str, Any]) -> int:
    if not args.normal_only:
        manifest["abort_reason"] = "--normal-only is required for normal live executor"
        write_json(out_dir / "run_manifest.json", manifest)
        return 2
    if os.environ.get("CONFIRM_NORMAL_SMOKE") != "YES":
        manifest["abort_reason"] = "CONFIRM_NORMAL_SMOKE=YES is required"
        write_json(out_dir / "run_manifest.json", manifest)
        return 2
    manifest["live_execution_started"] = True
    write_json(out_dir / "run_manifest.json", manifest)
    profiles = calibration_profiles(cfg) if args.calibrate_normal else [normal_smoke_profile(cfg)]
    rows = []
    rc = 0
    for idx, profile in enumerate(profiles, start=1):
        label = f"calibration_level{idx}_rps{profile['target_rps']}" if args.calibrate_normal else "normal_smoke"
        run_dir, level_rc = run_normal_level(cfg, out_dir, profile, label)
        rows.append({"level": idx, "target_rps": profile["target_rps"], "run_dir": str(run_dir), "returncode": level_rc})
        if level_rc != 0:
            rc = level_rc
            if args.calibrate_normal:
                break
    write_json(out_dir / "normal_live_runs.json", {"runs": rows})
    if args.calibrate_normal and CALIBRATION_ANALYZER.exists():
        analysis_dir = out_dir / "calibration_analysis"
        subprocess.run(
            [
                sys.executable,
                str(CALIBRATION_ANALYZER),
                "--input-root",
                str(out_dir),
                "--out-dir",
                str(analysis_dir),
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    return rc


def run(args: argparse.Namespace) -> int:
    modes = (args.dry_run, args.preflight_only, args.run_campaign, args.run_normal_smoke, args.calibrate_normal)
    if sum(bool(x) for x in modes) != 1:
        print("choose exactly one of --dry-run, --preflight-only, --run-campaign, --run-normal-smoke, --calibrate-normal", file=sys.stderr)
        return 2
    cfg = load_json(Path(args.config))
    live_normal = bool(args.run_normal_smoke or args.calibrate_normal)
    strict = bool(args.run_campaign or live_normal)
    errors, warnings = validate_config(cfg, strict=strict, live_normal=live_normal)
    if args.run_campaign:
        errors.append("cooling-constrained live campaign executor not implemented.")
    if args.run_campaign and os.environ.get("CONFIRM_EXPERIMENT") != "YES":
        errors.append("CONFIRM_EXPERIMENT=YES is required for --run-campaign")
    if live_normal and not args.normal_only:
        errors.append("--normal-only is required for normal-only live smoke/calibration")
    if live_normal and os.environ.get("CONFIRM_NORMAL_SMOKE") != "YES":
        errors.append("CONFIRM_NORMAL_SMOKE=YES is required for normal-only live smoke/calibration")
    if not CLIENT_SCRIPT.exists():
        errors.append(f"missing open-loop client script: {CLIENT_SCRIPT}")

    out_root = Path(args.out_root or DEFAULT_OUT_ROOT)
    out_dir = out_root / datetime.now().strftime("dryrun_%Y%m%d_%H%M%S")
    raw_run_dirs_before = discover_raw_run_dirs(RESULTS_ROOT)
    raw_before = collect_tree_fingerprint(RESULTS_ROOT, raw_run_dirs_before)
    manifest = build_manifest(args, cfg, errors, warnings)
    if errors:
        manifest["abort_reason"] = "; ".join(errors)
    write_json(out_dir / "run_manifest.json", manifest)
    write_execution_plan(out_dir, manifest)
    raw_after = collect_tree_fingerprint(RESULTS_ROOT, raw_run_dirs_before)
    preservation = {
        "checked_root": str(RESULTS_ROOT),
        "checked_raw_run_dirs": [str(p.relative_to(RESULTS_ROOT)) for p in raw_run_dirs_before],
        "raw_file_count_before": len(raw_before),
        "raw_file_count_after": len(raw_after),
        "raw_results_modified_by_preflight": raw_before != raw_after,
        "note": "only raw RUN_ID directories that existed before this planner/preflight run are fingerprinted; planner output directories are excluded",
    }
    write_json(out_dir / "raw_data_preservation_check.json", preservation)

    status = {
        "out_dir": str(out_dir),
        "errors": errors,
        "warnings": warnings,
        "planned_runs": len(manifest["planned_matrix"]),
        "live_execution_started": False,
    }
    print(json.dumps(status, indent=2, ensure_ascii=False))
    if errors:
        return 1
    if live_normal:
        return run_live_normal(args, cfg, out_dir, manifest)
    return 0


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--out-root")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--preflight-only", action="store_true")
    p.add_argument("--normal-only", action="store_true")
    p.add_argument("--run-campaign", action="store_true")
    p.add_argument("--run-normal-smoke", action="store_true")
    p.add_argument("--calibrate-normal", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
