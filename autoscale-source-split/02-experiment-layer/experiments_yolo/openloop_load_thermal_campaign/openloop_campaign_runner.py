#!/usr/bin/env python3
"""Open-loop normal-cooling planner, preflight, and guarded normal-only executor.

Cooling-constrained live campaign execution is intentionally not implemented here.
Only normal-cooling smoke/calibration can run live, and only with
--normal-only plus CONFIRM_NORMAL_SMOKE=YES.

Matched cooling-constrained pilot configs can be dry-run/preflighted to produce
reviewable safety and recovery artifacts. They cannot execute live cooling
control from this runner.
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
from datetime import datetime, timedelta, timezone
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
        v2 = cfg.get("normal_baseline_v2", {})
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
        for key in ("campaign_id", "replicate_id", "run_order"):
            if v2.get(key) is None:
                errors.append(f"normal_baseline_v2.{key} is required for v2 live normal collection")
        for key in ("warmup_duration_s", "measurement_duration_s", "post_observation_duration_s"):
            if v2.get(key) is None:
                errors.append(f"normal_baseline_v2.{key} is required for v2 live normal collection")
            elif float(v2.get(key, 0)) < 0:
                errors.append(f"normal_baseline_v2.{key} must be non-negative")
        if float(v2.get("measurement_duration_s", 0) or 0) <= 0:
            errors.append("normal_baseline_v2.measurement_duration_s must be positive")
        latency_policy = cfg.get("latency_target_policy", {})
        if not latency_policy:
            errors.append("latency_target_policy is required for v2 live normal collection")
        elif str(latency_policy.get("primary_latency_target", "")).lower() not in {"rolling_median", "rolling_mean"}:
            errors.append("latency_target_policy.primary_latency_target must be rolling_median or rolling_mean")
    return errors, warnings


def _as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def load_readiness_evidence(path_value: Any) -> Dict[str, Any]:
    path = Path(str(path_value or ""))
    if not path:
        return {}
    if not path.is_absolute():
        path = ROOT / path
    if path.is_dir():
        path = path / "analysis_manifest.json"
    if not path.exists():
        return {"evidence_found": False, "path": str(path)}
    try:
        payload = load_json(path)
        payload["evidence_found"] = True
        payload["path"] = str(path)
        return payload
    except Exception as exc:
        return {"evidence_found": False, "path": str(path), "error": str(exc)}


def validate_matched_pilot_config(cfg: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Validate design/preflight requirements for a matched cooling pilot.

    This validator does not authorize live execution. It only checks whether a
    pilot design is reviewable and aligned with the frozen long-normal policy.
    """
    errors: List[str] = []
    warnings: List[str] = []
    pilot = cfg.get("matched_cooling_constrained_pilot", {})
    if not pilot:
        return errors, warnings

    required = (
        "pilot_id",
        "matched_normal_campaign_id",
        "target_offered_rps",
        "max_inflight",
        "timeout_s",
        "payload_mix",
        "warmup_duration_s",
        "measurement_duration_s",
        "post_observation_duration_s",
        "run_local_healthy_calibration_window_s",
        "control_plan",
    )
    for key in required:
        if pilot.get(key) in (None, "", []):
            errors.append(f"matched_cooling_constrained_pilot.{key} is required")

    expected = {
        "warmup_duration_s": 180.0,
        "measurement_duration_s": 900.0,
        "post_observation_duration_s": 30.0,
        "run_local_healthy_calibration_window_s": 180.0,
    }
    for key, value in expected.items():
        observed = _as_float(pilot.get(key))
        if observed != value:
            errors.append(f"matched_cooling_constrained_pilot.{key} must be {value:g} to match frozen r07-r09 policy")

    if _as_float(pilot.get("target_offered_rps"), 0) <= 0:
        errors.append("matched_cooling_constrained_pilot.target_offered_rps must be positive")
    if _as_int(pilot.get("max_inflight"), 0) <= 0:
        errors.append("matched_cooling_constrained_pilot.max_inflight must be positive")
    if _as_float(pilot.get("timeout_s"), 0) <= 0:
        errors.append("matched_cooling_constrained_pilot.timeout_s must be positive")

    conditions = cfg.get("cooling_conditions", {})
    cooling = conditions.get("cooling_constrained")
    if not isinstance(cooling, dict):
        errors.append("cooling_conditions.cooling_constrained is required for matched pilot design")
    elif not bool(cooling.get("fan_control_allowed")):
        errors.append("cooling_conditions.cooling_constrained.fan_control_allowed must be true for experimental pilot metadata")
    if "normal_cooling" not in conditions:
        errors.append("cooling_conditions.normal_cooling is required as matched control")

    safety = cfg.get("safety", {})
    if safety.get("operator_max_gpu_temp_c") is None:
        errors.append("safety.operator_max_gpu_temp_c is required for matched pilot preflight")
    if safety.get("restore_mode") != "GPU_DEFAULT":
        errors.append("safety.restore_mode must be GPU_DEFAULT for matched pilot fail-closed cleanup")
    if not bool(safety.get("abort_on_control_command_failure", True)):
        errors.append("safety.abort_on_control_command_failure must remain true for matched pilot")
    if not bool(safety.get("abort_on_missing_gpu_telemetry", True)):
        errors.append("safety.abort_on_missing_gpu_telemetry must remain true for matched pilot")

    background = cfg.get("background_workload", {})
    if bool(background.get("control_enabled", False)):
        errors.append("matched pilot runner must not enable background workload control")
    if any(str(background.get(k, "")).lower() in {"scale", "restart", "delete"} for k in background):
        errors.append("background workload metadata must not request Kubernetes scale/restart/delete")

    control_plan = pilot.get("control_plan", {})
    if control_plan.get("restore_target") != "GPU_DEFAULT":
        errors.append("matched_cooling_constrained_pilot.control_plan.restore_target must be GPU_DEFAULT")
    if not bool(control_plan.get("original_state_capture_required")):
        errors.append("matched_cooling_constrained_pilot.control_plan.original_state_capture_required must be true")
    if not bool(control_plan.get("restore_on_abort_required")):
        errors.append("matched_cooling_constrained_pilot.control_plan.restore_on_abort_required must be true")
    if not bool(control_plan.get("control_event_log_required")):
        errors.append("matched_cooling_constrained_pilot.control_plan.control_event_log_required must be true")
    backend = str(control_plan.get("control_backend", ""))
    if backend and backend not in {"cooling-only-ssh-supervisor", "reviewed-operator-cooling-profile-placeholder"}:
        warnings.append(f"unrecognized matched pilot control backend: {backend}")
    if bool(control_plan.get("live_control_implemented")) and backend != "cooling-only-ssh-supervisor":
        errors.append("live cooling control requires control_plan.control_backend=cooling-only-ssh-supervisor")
    if backend == "cooling-only-ssh-supervisor":
        telemetry = cfg.get("telemetry_runtime", {})
        if not telemetry.get("nvidia_smi_ssh_alias"):
            errors.append("telemetry_runtime.nvidia_smi_ssh_alias is required for cooling-only SSH supervisor")
        if not control_plan.get("worker_repo"):
            errors.append("matched_cooling_constrained_pilot.control_plan.worker_repo is required for cooling-only SSH supervisor")

    evidence_cfg = pilot.get("normal_readiness_evidence", {})
    required_decision = evidence_cfg.get("required_decision", "method_ready_but_live_cooling_executor_still_fail_closed")
    evidence = load_readiness_evidence(evidence_cfg.get("analysis_manifest_path") or evidence_cfg.get("analysis_dir"))
    if not evidence.get("evidence_found"):
        errors.append("matched_cooling_constrained_pilot.normal_readiness_evidence analysis_manifest is required")
    else:
        decision = evidence.get("decision")
        if decision != required_decision:
            errors.append(
                "matched_cooling_constrained_pilot.normal_readiness_evidence decision "
                f"must be {required_decision}, got {decision}"
            )
        contract = evidence.get("required_pilot_contract", {})
        for key, value in expected.items():
            if _as_float(contract.get(key)) != value:
                errors.append(f"normal readiness evidence required_pilot_contract.{key} must be {value:g}")
        if int(evidence.get("latency_episode_count_after_180s_calibration", -1)) != 0:
            errors.append("normal readiness evidence must have zero latency episodes after 180s calibration")
        if str(evidence.get("cooling_constrained_live_executor_status")) != "not_implemented_fail_closed":
            warnings.append("normal readiness evidence does not explicitly record live cooling executor as fail-closed")

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


def mode_name(args: argparse.Namespace, cfg: Optional[Dict[str, Any]] = None) -> str:
    if args.dry_run:
        return "dry_run"
    if args.preflight_only:
        return "preflight_only"
    if args.run_normal_smoke:
        return "normal_only_live_smoke"
    if args.calibrate_normal:
        return "normal_cooling_calibration"
    if cfg and cfg.get("matched_cooling_constrained_pilot"):
        return "matched_cooling_constrained_live_pilot"
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
        "live_executor_status": "normal_only_executor_available" if live_normal else (
            "matched_cooling_only_executor_available" if args.run_campaign and cfg.get("matched_cooling_constrained_pilot") else "cooling_constrained_executor_not_implemented"
        ),
        "execution_mode": mode_name(args, cfg),
        "confirm_experiment_env": os.environ.get("CONFIRM_EXPERIMENT", ""),
        "confirm_normal_smoke_env": os.environ.get("CONFIRM_NORMAL_SMOKE", ""),
        "no_fan_control_executed": not bool(args.run_campaign and cfg.get("matched_cooling_constrained_pilot")),
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
        "normal_baseline_v2": cfg.get("normal_baseline_v2", {}),
        "latency_target_policy": cfg.get("latency_target_policy", {}),
        "feature_schema": cfg.get("feature_schema", {}),
        "matched_cooling_constrained_pilot": cfg.get("matched_cooling_constrained_pilot", {}),
    }


def build_matched_pilot_artifacts(cfg: Dict[str, Any], validation_errors: List[str], validation_warnings: List[str]) -> Dict[str, Any]:
    pilot = cfg.get("matched_cooling_constrained_pilot", {})
    control_plan = pilot.get("control_plan", {})
    backend = control_plan.get("control_backend", "")
    live_ready = backend == "cooling-only-ssh-supervisor" and bool(control_plan.get("live_control_implemented"))
    evidence_cfg = pilot.get("normal_readiness_evidence", {})
    evidence = load_readiness_evidence(evidence_cfg.get("analysis_manifest_path") or evidence_cfg.get("analysis_dir"))
    duration_s = sum(
        _as_float(pilot.get(key), 0.0) or 0.0
        for key in ("warmup_duration_s", "measurement_duration_s", "post_observation_duration_s")
    )
    return {
        "artifact_version": "1.0",
        "created_at_utc": utc_now_iso(),
        "pilot_id": pilot.get("pilot_id"),
        "live_execution_authorized": False,
        "live_executor_status": "cooling_only_executor_available_requires_confirm_and_cc_password" if live_ready else "preflight_recovery_plan_only_live_control_not_implemented",
        "fail_closed_reason": "dry-run/preflight mode does not authorize live cooling control",
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings,
        "matched_design": {
            "normal_campaign_id": pilot.get("matched_normal_campaign_id"),
            "control_condition": pilot.get("control_condition", "normal_cooling"),
            "treatment_condition": pilot.get("treatment_condition", "cooling_constrained"),
            "target_offered_rps": pilot.get("target_offered_rps"),
            "max_inflight": pilot.get("max_inflight"),
            "timeout_s": pilot.get("timeout_s"),
            "payload_mix": pilot.get("payload_mix", []),
            "duration_s": duration_s,
            "endpoint": cfg.get("endpoint", {}),
            "node_gpu_identity": cfg.get("node_gpu_identity", {}),
            "yolo_model": cfg.get("yolo_model", ""),
            "container_image": cfg.get("container_image", ""),
            "background_workload_state": cfg.get("background_workload", {}),
        },
        "frozen_policy": {
            "warmup_duration_s": pilot.get("warmup_duration_s"),
            "measurement_duration_s": pilot.get("measurement_duration_s"),
            "post_observation_duration_s": pilot.get("post_observation_duration_s"),
            "run_local_healthy_calibration_window_s": pilot.get("run_local_healthy_calibration_window_s"),
            "primary_latency_scoring_after_calibration_only": True,
            "raw_cross_run_latency_residual_primary": False,
        },
        "normal_readiness_evidence": evidence,
        "safety": cfg.get("safety", {}),
        "control_plan": control_plan,
        "abort_conditions": pilot.get("abort_conditions", {}),
        "not_primary_model_features": [
            "phase",
            "fan_mode",
            "fan_speed",
            "intervention_flag",
            "run_id",
            "cycle_id",
            "elapsed_s",
            "profile_id",
        ],
    }


def write_matched_pilot_artifacts(
    out_dir: Path,
    cfg: Dict[str, Any],
    validation_errors: List[str],
    validation_warnings: List[str],
) -> None:
    if not cfg.get("matched_cooling_constrained_pilot"):
        return
    artifacts = build_matched_pilot_artifacts(cfg, validation_errors, validation_warnings)
    write_json(out_dir / "matched_cooling_pilot_preflight.json", artifacts)
    recovery = {
        "created_at_utc": utc_now_iso(),
        "pilot_id": artifacts.get("pilot_id"),
        "live_execution_authorized": False,
        "original_state_capture_required": True,
        "restore_target": "GPU_DEFAULT",
        "restore_on_abort_required": True,
        "restore_attempted": False,
        "restore_result": "not_needed_dry_run_or_preflight",
        "fail_closed_triggers": [
            "missing telemetry",
            "temperature over operator_max_gpu_temp_c",
            "timeout/error burst",
            "client max-inflight saturation",
            "control command failure",
            "data landing failure",
        ],
    }
    write_json(out_dir / "matched_cooling_recovery_plan.json", recovery)
    event = {
        "ts": utc_now_iso(),
        "event_type": "dry_run_preflight_only",
        "pilot_id": artifacts.get("pilot_id"),
        "live_control_executed": False,
        "fan_control_executed": False,
        "coolercontrol_executed": False,
        "kubernetes_control_executed": False,
        "restore_target": "GPU_DEFAULT",
    }
    with (out_dir / "control_event_log.dryrun.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    lines = [
        "# Matched Cooling-Constrained Pilot Preflight",
        "",
        f"- pilot_id: `{artifacts.get('pilot_id')}`",
        "- live execution authorized: `false`",
        f"- live executor status: `{artifacts.get('live_executor_status')}`",
        "- restore target: `GPU_DEFAULT`",
        f"- validation errors: `{len(validation_errors)}`",
        f"- validation warnings: `{len(validation_warnings)}`",
        "",
        "## Frozen Policy",
        "",
        "- warm-up / healthy calibration: `180s`",
        "- formal measurement: `900s`",
        "- post-observation: `30s`",
        "- latency residual scoring excludes the initial 180s calibration window",
        "",
        "## Safety Boundary",
        "",
        "- This artifact is a dry-run/preflight review package.",
        "- It does not run CoolerControl, fan control, Kubernetes control, GPU stress, or a cooling-constrained pilot.",
        "- Live `--run-campaign` requires `CONFIRM_EXPERIMENT=YES`, `CC_PASSWORD`, and the cooling-only SSH supervisor backend.",
        "- The live pilot executor does not start torch background load and does not run Kubernetes scale/restart/delete.",
    ]
    (out_dir / "MATCHED_COOLING_PILOT_PREFLIGHT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def image_set_hash(payload_mix: List[str]) -> str:
    h = hashlib.sha256()
    for item in sorted(str(x) for x in payload_mix):
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        h.update(str(path).encode("utf-8"))
        if path.exists() and path.is_file():
            try:
                h.update(path.read_bytes())
            except OSError:
                pass
    return h.hexdigest()


def boundary_timestamps(start: datetime, warmup_s: float, measurement_s: float, post_s: float) -> Dict[str, str]:
    warmup_start = start
    warmup_end = warmup_start + timedelta(seconds=warmup_s)
    measurement_start = warmup_end
    measurement_end = measurement_start + timedelta(seconds=measurement_s)
    post_end = measurement_end + timedelta(seconds=post_s)
    return {
        "warmup_start_ts": warmup_start.isoformat(),
        "warmup_end_ts": warmup_end.isoformat(),
        "measurement_start_ts": measurement_start.isoformat(),
        "measurement_end_ts": measurement_end.isoformat(),
        "client_start_ts": warmup_start.isoformat(),
        "client_stop_ts": post_end.isoformat(),
        "measurement_start_elapsed_s": warmup_s,
        "measurement_end_elapsed_s": warmup_s + measurement_s,
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
            "- Matched cooling-constrained pilot configs may be dry-run/preflighted to produce recovery-plan artifacts only.",
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
        str(telemetry.get("namespace", "")),
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


def ssh_alias(cfg: Dict[str, Any]) -> str:
    return str(cfg.get("telemetry_runtime", {}).get("nvidia_smi_ssh_alias", "") or "")


def worker_repo(cfg: Dict[str, Any]) -> str:
    pilot = cfg.get("matched_cooling_constrained_pilot", {})
    control = pilot.get("control_plan", {})
    return str(control.get("worker_repo", "") or "")


def remote_cooling_supervisor_code() -> str:
    return r'''
import csv
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from fan_control_lab.gpu_supervisor_80 import read_gpu_metrics, activate_mode, wait_for_mode_effect

cfg = json.loads(CFG_JSON)
run_dir = Path(cfg["remote_run_dir"])
run_dir.mkdir(parents=True, exist_ok=True)
events_path = run_dir / "events.csv"
thermal_path = run_dir / "thermal.csv"
metadata_path = run_dir / "metadata.json"
restore_mode = cfg.get("restore_mode", "GPU_DEFAULT")
abort = {"requested": False}

os.environ["CCTV_DAEMON_PASSWORD"] = cfg["cc_password"]

def now():
    return datetime.now().isoformat(timespec="seconds")

def event(writer, start, phase, event_name, detail=""):
    row = {
        "timestamp": now(),
        "elapsed_s": round(time.time() - start, 3),
        "phase": phase,
        "event": event_name,
        "detail": detail,
    }
    writer.writerow(row)
    return row

def on_signal(signum, frame):
    abort["requested"] = True

signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)

metadata = {
    "pilot_id": cfg.get("pilot_id"),
    "mode": "cooling_only_supervisor",
    "background_gpu_load_started": False,
    "warmup_duration_s": cfg["warmup_duration_s"],
    "measurement_duration_s": cfg["measurement_duration_s"],
    "post_observation_duration_s": cfg["post_observation_duration_s"],
    "cooling_profile_mode": cfg["cooling_profile_mode"],
    "restore_mode": restore_mode,
    "operator_max_gpu_temp_c": cfg["operator_max_gpu_temp_c"],
    "started_at": now(),
}
metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

event_fields = ["timestamp", "elapsed_s", "phase", "event", "detail"]
thermal_fields = [
    "timestamp",
    "elapsed_s",
    "phase",
    "gpu_temp_c",
    "gpu_util_pct",
    "gpu_power_w",
    "gpu_fan_pct",
    "gpu_clock_mhz",
    "gpu_mem_clock_mhz",
    "active_mode",
    "abort_reason",
]

start = time.time()
restore_ok = False
abort_reason = ""
active_mode = ""

with events_path.open("w", newline="", encoding="utf-8") as ef, thermal_path.open("w", newline="", encoding="utf-8") as tf:
    ew = csv.DictWriter(ef, fieldnames=event_fields)
    tw = csv.DictWriter(tf, fieldnames=thermal_fields)
    ew.writeheader()
    tw.writeheader()

    def flush_event(phase, name, detail=""):
        row = event(ew, start, phase, name, detail)
        ef.flush()
        print(json.dumps(row, ensure_ascii=False), flush=True)

    def sample(phase):
        nonlocal_abort_reason = ""
        g = read_gpu_metrics()
        temp = g.get("gpu_temp_c")
        if temp is None:
            nonlocal_abort_reason = "missing_gpu_temperature"
        elif float(temp) > float(cfg["operator_max_gpu_temp_c"]):
            nonlocal_abort_reason = "gpu_temperature_over_operator_limit"
        row = {
            "timestamp": now(),
            "elapsed_s": round(time.time() - start, 3),
            "phase": phase,
            "gpu_temp_c": g.get("gpu_temp_c"),
            "gpu_util_pct": g.get("gpu_util_pct"),
            "gpu_power_w": g.get("gpu_power_w"),
            "gpu_fan_pct": g.get("gpu_fan_pct"),
            "gpu_clock_mhz": g.get("gpu_clock_mhz"),
            "gpu_mem_clock_mhz": g.get("gpu_mem_clock_mhz"),
            "active_mode": active_mode,
            "abort_reason": nonlocal_abort_reason,
        }
        tw.writerow(row)
        tf.flush()
        print(json.dumps(row, ensure_ascii=False), flush=True)
        return nonlocal_abort_reason

    def run_phase(phase, seconds, mode):
        global active_mode
        flush_event(phase, "activate_mode_request", mode)
        activate_mode(mode)
        ok = wait_for_mode_effect(mode, timeout=20)
        active_mode = mode
        flush_event(phase, "activate_mode_result", f"{mode}, ok={ok}")
        if not ok:
            return f"mode_effect_failed:{mode}"
        phase_start = time.time()
        while time.time() - phase_start < float(seconds):
            if abort["requested"]:
                return "signal_abort"
            reason = sample(phase)
            if reason:
                return reason
            time.sleep(float(cfg.get("sample_interval_s", 1.0)))
        flush_event(phase, "phase_end", "")
        return ""

    try:
        abort_reason = run_phase("warmup_healthy_calibration", cfg["warmup_duration_s"], cfg.get("baseline_mode", "GPU_DEFAULT"))
        if not abort_reason:
            abort_reason = run_phase("cooling_constrained_measurement", cfg["measurement_duration_s"], cfg["cooling_profile_mode"])
        if not abort_reason:
            abort_reason = run_phase("post_observation_restore", cfg["post_observation_duration_s"], restore_mode)
    except Exception as exc:
        abort_reason = f"exception:{exc}"
        flush_event("exception", "exception", str(exc))
    finally:
        try:
            flush_event("finalize", "restore_mode_request", restore_mode)
            activate_mode(restore_mode)
            restore_ok = wait_for_mode_effect(restore_mode, timeout=20)
            active_mode = restore_mode
            flush_event("finalize", "restore_mode_result", f"{restore_mode}, ok={restore_ok}")
        except Exception as exc:
            flush_event("finalize", "restore_mode_failed", str(exc))

summary = {
    "completed": not bool(abort_reason),
    "abort_reason": abort_reason,
    "restore_mode": restore_mode,
    "restore_ok": restore_ok,
    "finished_at": now(),
}
(run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
sys.exit(0 if summary["completed"] and restore_ok else 2)
'''


def start_cooling_supervisor(cfg: Dict[str, Any], run_dir: Path, remote_run_id: str) -> subprocess.Popen:
    pilot = cfg.get("matched_cooling_constrained_pilot", {})
    control = pilot.get("control_plan", {})
    cc_password = os.environ.get("CC_PASSWORD", "")
    if not cc_password:
        raise RuntimeError("CC_PASSWORD is required for matched cooling pilot live executor")
    remote_dir = f"{worker_repo(cfg).rstrip('/')}/fan_control_lab/logs/{remote_run_id}"
    profile_mode = str(control.get("cooling_profile_mode") or pilot.get("cooling_profile_mode") or "GPU_FAULT_5")
    payload = {
        "pilot_id": pilot.get("pilot_id"),
        "remote_run_dir": remote_dir,
        "cc_password": cc_password,
        "warmup_duration_s": pilot.get("warmup_duration_s"),
        "measurement_duration_s": pilot.get("measurement_duration_s"),
        "post_observation_duration_s": pilot.get("post_observation_duration_s"),
        "baseline_mode": control.get("baseline_mode", "GPU_DEFAULT"),
        "cooling_profile_mode": profile_mode,
        "restore_mode": control.get("restore_target", "GPU_DEFAULT"),
        "operator_max_gpu_temp_c": cfg.get("safety", {}).get("operator_max_gpu_temp_c"),
        "sample_interval_s": control.get("sample_interval_s", 1.0),
    }
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=5",
        ssh_alias(cfg),
        (
            f"cd {worker_repo(cfg)} && "
            "source ../gpu-tempctl-1080ti/bin/activate && "
            "source fan_control_lab/env.sh && "
            "source $HOME/.cargo/env && "
            "export MPLCONFIGDIR=$HOME/.config/matplotlib && mkdir -p $MPLCONFIGDIR && "
            "python -"
        ),
    ]
    log = (run_dir / "cooling_supervisor.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=ROOT,
        text=True,
    )
    assert proc.stdin is not None
    proc.stdin.write("CFG_JSON = " + repr(json.dumps(payload, separators=(",", ":"))) + "\n")
    proc.stdin.write(remote_cooling_supervisor_code())
    proc.stdin.close()
    write_json(run_dir / "cooling_supervisor_launch.json", {k: v for k, v in payload.items() if k != "cc_password"})
    return proc


def restore_gpu_default(cfg: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    cc_password = os.environ.get("CC_PASSWORD", "")
    result = {"attempted": False, "ok": False, "error": ""}
    if not cc_password:
        result["error"] = "missing CC_PASSWORD"
        write_json(run_dir / "cooling_restore_attempt.json", result)
        return result
    payload = {"cc_password": cc_password}
    code = (
        "import json, os, sys\n"
        "cfg=json.loads(CFG_JSON)\n"
        "os.environ['CCTV_DAEMON_PASSWORD']=cfg['cc_password']\n"
        "from fan_control_lab.gpu_supervisor_80 import activate_mode, wait_for_mode_effect\n"
        "activate_mode('GPU_DEFAULT')\n"
        "ok=wait_for_mode_effect('GPU_DEFAULT', timeout=20)\n"
        "print(json.dumps({'ok': ok}))\n"
        "sys.exit(0 if ok else 2)\n"
    )
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=5",
        ssh_alias(cfg),
        (
            f"cd {worker_repo(cfg)} && "
            "source ../gpu-tempctl-1080ti/bin/activate && "
            "source fan_control_lab/env.sh && "
            "source $HOME/.cargo/env && "
            "python -"
        ),
    ]
    try:
        p = subprocess.run(
            cmd,
            input="CFG_JSON = " + repr(json.dumps(payload, separators=(",", ":"))) + "\n" + code,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=45,
        )
        result.update({"attempted": True, "ok": p.returncode == 0, "stdout": p.stdout[-1000:], "stderr": p.stderr[-1000:]})
    except Exception as exc:
        result.update({"attempted": True, "ok": False, "error": str(exc)})
    write_json(run_dir / "cooling_restore_attempt.json", result)
    return result


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
    v2 = cfg.get("normal_baseline_v2", {})
    warmup_s = float(v2.get("warmup_duration_s", 0) or 0)
    measurement_s = float(v2.get("measurement_duration_s", profile.get("duration_s", 0)) or 0)
    post_s = float(v2.get("post_observation_duration_s", cfg.get("telemetry_runtime", {}).get("tail_seconds", 0)) or 0)
    collection_profile = dict(profile)
    collection_profile["duration_s"] = warmup_s + measurement_s + post_s
    collection_start = datetime.now(timezone.utc)
    boundaries = boundary_timestamps(collection_start, warmup_s, measurement_s, post_s)
    payload_mix = collection_profile.get("payload_mix") or cfg.get("normal_live_smoke", {}).get("payload_mix") or []
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "created_at_utc": utc_now_iso(),
            "execution_mode": "normal_cooling_live_level",
            "cooling_condition": "normal_cooling",
            "analysis_ineligible": False,
            "campaign_id": v2.get("campaign_id"),
            "replicate_id": v2.get("replicate_id"),
            "target_offered_rps": collection_profile.get("target_rps"),
            "run_order": v2.get("run_order"),
            **boundaries,
            "no_fan_control_executed": True,
            "no_coolercontrol_executed": True,
            "no_kubernetes_scale_restart_delete_executed": True,
            "endpoint": cfg.get("endpoint", {}),
            "endpoint_identity": cfg.get("endpoint", {}),
            "offered_load_profile": collection_profile,
            "safety": cfg.get("safety", {}),
            "telemetry_runtime": cfg.get("telemetry_runtime", {}),
            "telemetry_source_availability": cfg.get("telemetry_sources", {}),
            "telemetry_sample_age_summary": {},
            "model": cfg.get("yolo_model", ""),
            "container_image": cfg.get("container_image", ""),
            "image_set_hash": image_set_hash(payload_mix),
            "node_gpu_identity": cfg.get("node_gpu_identity", {}),
            "background_workload_state": cfg.get("background_workload", {}),
            "latency_target_policy": cfg.get("latency_target_policy", {}),
        },
    )
    duration_s = int(float(collection_profile["duration_s"])) + int(cfg.get("telemetry_runtime", {}).get("tail_seconds", 5))
    vm_proc = start_vm_collector(cfg, run_dir, duration_s)
    smi_proc = start_nvidia_smi_monitor(cfg, run_dir)
    abort = {"started_at_utc": utc_now_iso(), "abort_reason": "", "completed": False}
    write_json(run_dir / "safety_abort_record.json", abort)
    rc = 1
    try:
        rc = run_open_loop_client(cfg, collection_profile, run_dir)
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
    telemetry_summary = detail.get("telemetry", summarize_telemetry(run_dir))
    write_json(run_dir / "telemetry_availability_summary.json", telemetry_summary)
    manifest_path = run_dir / "run_manifest.json"
    manifest = load_json(manifest_path)
    manifest["telemetry_sample_age_summary"] = telemetry_summary
    if should_abort:
        manifest["analysis_ineligible"] = True
        manifest["analysis_ineligible_reason"] = ";".join(reasons)
    write_json(manifest_path, manifest)
    return run_dir, rc


def sync_cooling_logs(cfg: Dict[str, Any], run_dir: Path, remote_run_id: str) -> None:
    remote_dir = f"{worker_repo(cfg).rstrip('/')}/fan_control_lab/logs/{remote_run_id}/"
    local_dir = run_dir / "worker_cooling_logs"
    local_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "rsync",
        "-e",
        "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5",
        "-av",
        f"{ssh_alias(cfg)}:{remote_dir}",
        str(local_dir) + "/",
    ]
    try:
        p = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=60)
        write_json(
            run_dir / "worker_cooling_logs_sync.json",
            {
                "remote_dir": remote_dir,
                "local_dir": str(local_dir),
                "returncode": p.returncode,
                "stdout_tail": p.stdout[-2000:],
                "stderr_tail": p.stderr[-2000:],
            },
        )
    except Exception as exc:
        write_json(run_dir / "worker_cooling_logs_sync.json", {"remote_dir": remote_dir, "local_dir": str(local_dir), "error": str(exc)})


def matched_pilot_profile(cfg: Dict[str, Any]) -> Dict[str, Any]:
    pilot = cfg.get("matched_cooling_constrained_pilot", {})
    duration_s = (
        float(pilot.get("warmup_duration_s", 0) or 0)
        + float(pilot.get("measurement_duration_s", 0) or 0)
        + float(pilot.get("post_observation_duration_s", 0) or 0)
    )
    return {
        "target_rps": pilot.get("target_offered_rps"),
        "duration_s": duration_s,
        "max_inflight": pilot.get("max_inflight"),
        "timeout_s": pilot.get("timeout_s", 10),
        "payload_mix": pilot.get("payload_mix", []),
    }


def run_matched_cooling_pilot(cfg: Dict[str, Any], out_dir: Path, manifest: Dict[str, Any]) -> int:
    if os.environ.get("CONFIRM_EXPERIMENT") != "YES":
        manifest["abort_reason"] = "CONFIRM_EXPERIMENT=YES is required"
        write_json(out_dir / "run_manifest.json", manifest)
        return 2
    if not os.environ.get("CC_PASSWORD"):
        manifest["abort_reason"] = "CC_PASSWORD is required for matched cooling pilot"
        write_json(out_dir / "run_manifest.json", manifest)
        return 2
    pilot = cfg.get("matched_cooling_constrained_pilot", {})
    control = pilot.get("control_plan", {})
    if control.get("control_backend") != "cooling-only-ssh-supervisor":
        manifest["abort_reason"] = "control_backend must be cooling-only-ssh-supervisor"
        write_json(out_dir / "run_manifest.json", manifest)
        return 2

    run_dir = out_dir / f"matched_cooling_pilot_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    profile = matched_pilot_profile(cfg)
    start = datetime.now(timezone.utc)
    boundaries = boundary_timestamps(
        start,
        float(pilot.get("warmup_duration_s", 0) or 0),
        float(pilot.get("measurement_duration_s", 0) or 0),
        float(pilot.get("post_observation_duration_s", 0) or 0),
    )
    payload_mix = profile.get("payload_mix", [])
    remote_run_id = f"{pilot.get('pilot_id', 'matched_cooling_pilot')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_manifest = {
        "schema_version": "2.1",
        "run_id": run_dir.name,
        "created_at_utc": utc_now_iso(),
        "execution_mode": "matched_cooling_constrained_live_pilot",
        "cooling_condition": "cooling_constrained",
        "analysis_ineligible": False,
        "campaign_id": pilot.get("pilot_id"),
        "replicate_id": pilot.get("replicate_id", "pilot_r01"),
        "target_offered_rps": profile.get("target_rps"),
        "run_order": pilot.get("run_order", 1),
        **boundaries,
        "live_execution_started": True,
        "no_fan_control_executed": False,
        "no_coolercontrol_executed": False,
        "no_kubernetes_scale_restart_delete_executed": True,
        "no_background_gpu_load_started_by_runner": True,
        "endpoint": cfg.get("endpoint", {}),
        "endpoint_identity": cfg.get("endpoint", {}),
        "offered_load_profile": profile,
        "matched_cooling_constrained_pilot": pilot,
        "safety": cfg.get("safety", {}),
        "telemetry_runtime": cfg.get("telemetry_runtime", {}),
        "telemetry_source_availability": cfg.get("telemetry_sources", {}),
        "telemetry_sample_age_summary": {},
        "model": cfg.get("yolo_model", ""),
        "container_image": cfg.get("container_image", ""),
        "image_set_hash": image_set_hash(payload_mix),
        "node_gpu_identity": cfg.get("node_gpu_identity", {}),
        "background_workload_state": cfg.get("background_workload", {}),
        "latency_target_policy": {
            "primary_latency_scoring_after_calibration_only": True,
            "run_local_healthy_calibration_window_s": pilot.get("run_local_healthy_calibration_window_s"),
        },
        "remote_cooling_run_id": remote_run_id,
    }
    write_json(run_dir / "run_manifest.json", run_manifest)
    write_json(run_dir / "safety_abort_record.json", {"started_at_utc": utc_now_iso(), "abort_reason": "", "completed": False})

    duration_s = int(float(profile["duration_s"])) + int(cfg.get("telemetry_runtime", {}).get("tail_seconds", 5))
    vm_proc = start_vm_collector(cfg, run_dir, duration_s)
    smi_proc = start_nvidia_smi_monitor(cfg, run_dir)
    cooling_proc: subprocess.Popen | None = None
    rc = 1
    reasons: List[str] = []
    detail: Dict[str, Any] = {}
    try:
        cooling_proc = start_cooling_supervisor(cfg, run_dir, remote_run_id)
        rc = run_open_loop_client(cfg, profile, run_dir)
        if rc != 0:
            reasons.append(f"open_loop_client_failed:{rc}")
        cooling_rc = cooling_proc.wait(timeout=max(60, duration_s + 120))
        write_json(run_dir / "cooling_supervisor_returncode.json", {"returncode": cooling_rc})
        if cooling_rc != 0:
            reasons.append(f"cooling_supervisor_failed:{cooling_rc}")
    except subprocess.TimeoutExpired:
        reasons.append("cooling_supervisor_timeout")
        if cooling_proc:
            stop_process(cooling_proc, timeout_s=5)
    except Exception as exc:
        reasons.append(f"exception:{exc}")
        append_abort(run_dir, "matched_pilot_exception", {"error": str(exc)})
    finally:
        stop_process(vm_proc)
        stop_process(smi_proc)
        restore = restore_gpu_default(cfg, run_dir)
        sync_cooling_logs(cfg, run_dir, remote_run_id)

    should_abort, eval_reasons, detail = evaluate_abort_conditions(run_dir, cfg)
    reasons.extend(eval_reasons if should_abort else [])
    if reasons:
        append_abort(run_dir, "matched_pilot_abort_or_quality_failure", {"reasons": reasons, **detail})
    telemetry_summary = detail.get("telemetry", summarize_telemetry(run_dir))
    write_json(run_dir / "telemetry_availability_summary.json", telemetry_summary)
    run_manifest["telemetry_sample_age_summary"] = telemetry_summary
    if reasons:
        run_manifest["analysis_ineligible"] = True
        run_manifest["analysis_ineligible_reason"] = ";".join(reasons)
    write_json(run_dir / "run_manifest.json", run_manifest)
    write_json(
        run_dir / "safety_abort_record.json",
        {
            "completed": not reasons,
            "finished_at_utc": utc_now_iso(),
            "abort_reason": ";".join(reasons),
            "restore_attempted": True,
        },
    )
    write_json(out_dir / "matched_cooling_live_runs.json", {"runs": [{"run_dir": str(run_dir), "returncode": 0 if not reasons else 1, "abort_reasons": reasons}]})
    manifest["live_execution_started"] = True
    manifest["abort_reason"] = ";".join(reasons)
    write_json(out_dir / "run_manifest.json", manifest)
    return 0 if not reasons else 1


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
    pilot_errors, pilot_warnings = validate_matched_pilot_config(cfg)
    errors.extend(pilot_errors)
    warnings.extend(pilot_warnings)
    if args.run_campaign:
        if not cfg.get("matched_cooling_constrained_pilot"):
            errors.append("cooling-constrained live campaign executor not implemented.")
        elif cfg.get("matched_cooling_constrained_pilot", {}).get("control_plan", {}).get("control_backend") != "cooling-only-ssh-supervisor":
            errors.append("matched cooling pilot live executor requires control_backend=cooling-only-ssh-supervisor")
        elif os.environ.get("CC_PASSWORD") is None:
            errors.append("CC_PASSWORD is required for matched cooling pilot live executor")
    if args.run_campaign and os.environ.get("CONFIRM_EXPERIMENT") != "YES":
        errors.append("CONFIRM_EXPERIMENT=YES is required for --run-campaign")
    if live_normal and not args.normal_only:
        errors.append("--normal-only is required for normal-only live smoke/calibration")
    if live_normal and os.environ.get("CONFIRM_NORMAL_SMOKE") != "YES":
        errors.append("CONFIRM_NORMAL_SMOKE=YES is required for normal-only live smoke/calibration")
    if not CLIENT_SCRIPT.exists():
        errors.append(f"missing open-loop client script: {CLIENT_SCRIPT}")

    out_root = Path(args.out_root or DEFAULT_OUT_ROOT)
    out_dir = out_root / datetime.now().strftime("dryrun_%Y%m%d_%H%M%S_%f")
    raw_run_dirs_before = discover_raw_run_dirs(RESULTS_ROOT)
    raw_before = collect_tree_fingerprint(RESULTS_ROOT, raw_run_dirs_before)
    manifest = build_manifest(args, cfg, errors, warnings)
    if errors:
        manifest["abort_reason"] = "; ".join(errors)
    write_json(out_dir / "run_manifest.json", manifest)
    write_execution_plan(out_dir, manifest)
    write_matched_pilot_artifacts(out_dir, cfg, pilot_errors, pilot_warnings)
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
    if errors:
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 1
    if live_normal:
        rc = run_live_normal(args, cfg, out_dir, manifest)
        final_manifest = load_json(out_dir / "run_manifest.json")
        status["live_execution_started"] = bool(final_manifest.get("live_execution_started"))
        status["returncode"] = rc
        normal_runs_path = out_dir / "normal_live_runs.json"
        if normal_runs_path.exists():
            status["normal_live_runs"] = load_json(normal_runs_path).get("runs", [])
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return rc
    if args.run_campaign and cfg.get("matched_cooling_constrained_pilot"):
        rc = run_matched_cooling_pilot(cfg, out_dir, manifest)
        final_manifest = load_json(out_dir / "run_manifest.json")
        status["live_execution_started"] = bool(final_manifest.get("live_execution_started"))
        status["returncode"] = rc
        live_runs_path = out_dir / "matched_cooling_live_runs.json"
        if live_runs_path.exists():
            status["matched_cooling_live_runs"] = load_json(live_runs_path).get("runs", [])
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return rc
    print(json.dumps(status, indent=2, ensure_ascii=False))
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
