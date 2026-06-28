import csv
import json
import subprocess
import time
from pathlib import Path

from app.schemas.experiment import (
    FanCycleCommandPreview,
    FanCycleConfig,
    FanCycleCurrentMetrics,
    FanCycleEvent,
    FanCycleLatestResponse,
    FanCycleLiveResponse,
    FanCyclePhaseSummary,
    FanCycleRunInfo,
    FanCycleTimeseriesPoint,
)
from app.services.cache_service import SimpleTTLCache
from app.services.experiment_runtime import load_experiment_runtime_config
from app.services.yolo_demo_service import RUNS_ROOT as YOLO_DEMO_RUNS_ROOT
from app.services.yolo_demo_service import YoloDemoService

CONFIG = load_experiment_runtime_config()
RESULTS_ROOT = CONFIG.fan_cycle_results_root
def _to_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(float(value))


def _to_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _read_kv_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _sample_rows(rows: list[dict[str, str]], max_points: int = 320) -> list[dict[str, str]]:
    if len(rows) <= max_points:
        return rows

    step = max(1, len(rows) // max_points)
    sampled = rows[::step]
    if sampled[-1] != rows[-1]:
        sampled.append(rows[-1])
    return sampled


def _read_latest_csv_row(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8", newline="") as fh:
        header = fh.readline()
        if not header:
            return {}
        last_line = ""
        for line in fh:
            if line.strip():
                last_line = line
        if not last_line:
            return {}

    rows = list(csv.DictReader([header, last_line]))
    return rows[0] if rows else {}


def _run_command(args: list[str], timeout: float = 8.0) -> str:
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return completed.stdout.strip()


class FanCycleExperimentService:
    def __init__(self, cache: SimpleTTLCache | None = None) -> None:
        self.cache = cache or SimpleTTLCache()
        self.yolo_demo_service = YoloDemoService()

    def _find_latest_complete_run_dir(self) -> Path:
        candidates = sorted(
            [p for p in RESULTS_ROOT.iterdir() if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )
        for run_dir in candidates:
            if (run_dir / "aligned_serial_thermal.csv").exists():
                return run_dir
        raise FileNotFoundError("No completed fan-cycle experiment run found")

    def _find_latest_run_dir(self) -> Path:
        candidates = sorted(
            [p for p in RESULTS_ROOT.iterdir() if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )
        if candidates:
            return candidates[0]
        raise FileNotFoundError("No fan-cycle experiment run found")

    def _load_run_context(self) -> tuple[Path, dict[str, str], FanCycleRunInfo]:
        latest = self.get_latest()
        run_dir = RESULTS_ROOT / latest.run.run_id
        config_raw = _read_kv_file(run_dir / "experiment_config.txt")
        return run_dir, config_raw, latest.run

    def _resolve_node_ip(self, node_name: str) -> str | None:
        try:
            value = _run_command(
                [
                    "kubectl",
                    "get",
                    "node",
                    node_name,
                    "-o",
                    "jsonpath={.status.addresses[?(@.type=='InternalIP')].address}",
                ],
                timeout=5.0,
            )
            return value or None
        except Exception:
            return None

    def _gpu_probe_targets(self, node_name: str, node_ip: str | None) -> list[str]:
        targets: list[str] = []
        if CONFIG.node_ssh:
            targets.append(CONFIG.node_ssh)
        if node_ip:
            targets.append(f"{node_name}@{node_ip}")
        targets.append(node_name)

        unique_targets: list[str] = []
        seen: set[str] = set()
        for target in targets:
            if target and target not in seen:
                unique_targets.append(target)
                seen.add(target)
        return unique_targets

    def _probe_gpu_live_metrics(self, node_name: str, node_ip: str | None) -> dict[str, float]:
        query = (
            "nvidia-smi "
            "--query-gpu=temperature.gpu,utilization.gpu,fan.speed,clocks.sm "
            "--format=csv,noheader,nounits"
        )
        for ssh_target in self._gpu_probe_targets(node_name, node_ip):
            try:
                output = _run_command(
                    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", ssh_target, query],
                    timeout=8.0,
                )
                line = output.splitlines()[0]
                parts = [p.strip().rstrip(" %") for p in line.split(",")]
                return {
                    "gpu_temp_c": _to_float(parts[0]),
                    "gpu_util_pct": _to_float(parts[1]),
                    "fan_pct": _to_float(parts[2]),
                    "sm_clock_mhz": _to_float(parts[3]),
                }
            except Exception:
                continue
        return {}

    def _probe_latency_live_metrics(self, run_id: str) -> dict[str, float]:
        if not run_id:
            return {}

        latest_row = _read_latest_csv_row(YOLO_DEMO_RUNS_ROOT / run_id / "measurement_raw.csv")
        if not latest_row:
            return {}

        try:
            return {
                "server_latency_ms": _to_float(latest_row.get("server_latency_ms")),
                "e2e_latency_ms": _to_float(latest_row.get("e2e_latency_ms")),
            }
        except Exception:
            return {}

    def _infer_status(self, event_rows: list[dict[str, str]]) -> str:
        if not event_rows:
            return "unknown"

        last_event = event_rows[-1].get("event", "")
        last_phase = event_rows[-1].get("phase", "")
        if last_event == "restore_mode" or last_phase == "finalize":
            return "completed"
        return "running"

    def _build_events(
        self,
        event_rows: list[dict[str, str]],
        series_rows: list[dict[str, str]],
    ) -> list[FanCycleEvent]:
        events: list[FanCycleEvent] = []

        for row in event_rows:
            event = row.get("event", "")
            phase = row.get("phase", "")
            detail = row.get("detail", "")
            level = "info"
            message = f"{phase}: {event}"

            if event == "activate_mode":
                message = f"Fan mode activated: {detail}"
            elif event == "restore_mode":
                message = f"Recovery complete, fan restored to {detail}"
            elif event == "phase_start":
                message = f"Phase {phase} entered"
            elif event == "phase_end":
                message = f"Phase {phase} completed"
            elif event == "recovery_timeout":
                level = "warn"
                message = "Recovery timeout reached before stable band was restored"

            events.append(
                FanCycleEvent(
                    time=row.get("timestamp", ""),
                    level=level,
                    phase=phase,
                    event=event,
                    detail=detail,
                    message=message,
                )
            )

        threshold_added = False
        latency_added = False
        for row in series_rows:
            if not threshold_added and _to_float(row.get("gpu_temp_c")) >= 90:
                events.append(
                    FanCycleEvent(
                        time=row.get("timestamp", ""),
                        level="critical",
                        phase=row.get("phase", ""),
                        event="temp_threshold",
                        detail="gpu_temp_c>=90",
                        message="GPU temperature exceeded 90°C threshold",
                    )
                )
                threshold_added = True

            if not latency_added and _to_float(row.get("server_latency_ms")) >= 1000:
                events.append(
                    FanCycleEvent(
                        time=row.get("timestamp", ""),
                        level="warn",
                        phase=row.get("phase", ""),
                        event="latency_spike",
                        detail="server_latency_ms>=1000",
                        message="Server latency spike observed",
                    )
                )
                latency_added = True

            if threshold_added and latency_added:
                break

        events.sort(key=lambda item: item.time)
        return events

    def get_latest(self) -> FanCycleLatestResponse:
        cache_key = "fan_cycle_experiment::latest"
        cached = self.cache.get(cache_key, ttl_seconds=5)
        if cached is not None:
            return cached

        run_dir = self._find_latest_complete_run_dir()
        config_raw = _read_kv_file(run_dir / "experiment_config.txt")
        aligned_rows = _read_csv_rows(run_dir / "aligned_serial_thermal.csv")
        phase_rows = _read_csv_rows(run_dir / "cycle_phase_summary.csv")
        event_rows = _read_csv_rows(run_dir / "thermal_cycle" / "worker_logs" / "events.csv")
        summary_json = json.loads(
            (run_dir / "thermal_cycle" / "worker_logs" / "summary.json").read_text(encoding="utf-8")
        )
        nvidia_rows = _read_csv_rows(run_dir / "nvidia_smi_gpu_1s.csv")

        latest_row = aligned_rows[-1]
        sampled_rows = _sample_rows(aligned_rows)
        status = self._infer_status(event_rows)
        current_cycle = _to_int(latest_row.get("cycle_index"))
        current_phase = latest_row.get("phase", "unknown")
        target_node = (
            latest_row.get("server_node_name")
            or config_raw.get("WORKER_SSH", "").split("@", 1)[0]
            or "unknown"
        )
        gpu_name = (
            nvidia_rows[0].get(" name", "").strip()
            if nvidia_rows
            else "Unknown GPU"
        )

        response = FanCycleLatestResponse(
            schema_name="pre6g.experiments.fan_cycle.latest.v1",
            generated_at=int(time.time()),
            run=FanCycleRunInfo(
                run_id=config_raw.get("RUN_ID", run_dir.name),
                status=status,
                target_node=target_node,
                gpu_name=gpu_name,
                workload="YOLO26 single pod / closed-loop serial request",
                cycles=_to_int(config_raw.get("CYCLES"), 1),
                current_cycle=current_cycle,
                current_phase=current_phase,
                elapsed_seconds=_to_float(latest_row.get("elapsed_s")),
                focus_pod=config_raw.get("FOCUS_POD", ""),
                target_url=config_raw.get("TARGET_URL", ""),
            ),
            config=FanCycleConfig(
                normal_hold_seconds=_to_int(config_raw.get("NORMAL_HOLD_SECONDS"), 900),
                fault_hold_seconds=_to_int(config_raw.get("FAULT_HOLD_SECONDS"), 900),
                recovery_stable_seconds=_to_int(config_raw.get("RECOVERY_STABLE_SECONDS"), 60),
                recovery_max_seconds=_to_int(config_raw.get("RECOVERY_MAX_SECONDS"), 900),
                fixed_fan_pct=_to_int(config_raw.get("FIXED_FAN_PCT"), 5),
                normal_temp_min_c=_to_float(config_raw.get("NORMAL_TEMP_MIN_C"), 50.0),
                normal_temp_max_c=_to_float(config_raw.get("NORMAL_TEMP_MAX_C"), 70.0),
                fault_temp_target_c=_to_float(config_raw.get("FAULT_TEMP_TARGET_C"), 90.0),
                bg_size=_to_int(config_raw.get("BG_SIZE"), 4096),
                bg_duty=_to_float(config_raw.get("BG_DUTY"), 1.0),
                bg_period_ms=_to_int(config_raw.get("BG_PERIOD_MS"), 100),
            ),
            current=FanCycleCurrentMetrics(
                gpu_temp_c=_to_float(latest_row.get("gpu_temp_c")),
                fan_pct=_to_float(latest_row.get("gpu_fan_pct")),
                sm_clock_mhz=_to_float(latest_row.get("gpu_clock_mhz")),
                gpu_util_pct=_to_float(latest_row.get("gpu_util_pct")),
                server_latency_ms=_to_float(latest_row.get("server_latency_ms")),
                e2e_latency_ms=_to_float(latest_row.get("e2e_latency_ms")),
            ),
            command_preview=FanCycleCommandPreview(
                smoke_test=(
                    "cd /home/icclz2/Pre6G\n"
                    "CC_PASSWORD='your_coolercontrol_password' \\\n"
                    "CYCLES=1 \\\n"
                    "NORMAL_HOLD_SECONDS=300 \\\n"
                    "FAULT_HOLD_SECONDS=300 \\\n"
                    "RECOVERY_MAX_SECONDS=300 \\\n"
                    "bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh"
                ),
                full_experiment=(
                    "cd /home/icclz2/Pre6G\n"
                    "CC_PASSWORD='your_coolercontrol_password' \\\n"
                    "bash autoscale-source-split/02-experiment-layer/experiments_yolo/single_pod_bgload_fan_cycle/run_single_pod_bgload_fan_cycle.sh"
                ),
            ),
            phase_summary=[
                FanCyclePhaseSummary(
                    cycle_index=_to_int(row.get("cycle_index")),
                    phase=row.get("phase", "unknown"),
                    gpu_temp_c_mean=_to_float(row.get("gpu_temp_c_mean")),
                    gpu_temp_c_p95=_to_float(row.get("gpu_temp_c_p95")),
                    gpu_fan_pct_mean=_to_float(row.get("gpu_fan_pct_mean")),
                    gpu_util_pct_mean=_to_float(row.get("gpu_util_pct_mean")),
                    gpu_clock_mhz_mean=_to_float(row.get("gpu_clock_mhz_mean")),
                    server_latency_ms_p95=_to_float(row.get("server_latency_ms_p95")),
                    e2e_latency_ms_p95=_to_float(row.get("e2e_latency_ms_p95")),
                )
                for row in phase_rows
                if row.get("phase") != "unknown"
            ],
            timeseries=[
                FanCycleTimeseriesPoint(
                    time=row.get("timestamp", "").split("T", 1)[-1],
                    elapsed_s=_to_float(row.get("elapsed_s")),
                    cycle_index=_to_int(row.get("cycle_index")),
                    phase=row.get("phase", "unknown"),
                    gpu_temp=_to_float(row.get("gpu_temp_c")),
                    fan_pct=_to_float(row.get("gpu_fan_pct")),
                    sm_clock=_to_float(row.get("gpu_clock_mhz")),
                    gpu_util=_to_float(row.get("gpu_util_pct")),
                    server_latency=_to_float(row.get("server_latency_ms")),
                    e2e_latency=_to_float(row.get("e2e_latency_ms")),
                )
                for row in sampled_rows
            ],
            events=self._build_events(event_rows, aligned_rows),
        )

        self.cache.set(cache_key, response)
        return response

    def get_live(self) -> FanCycleLiveResponse:
        cache_key = "fan_cycle_experiment::live"
        cached = self.cache.get(cache_key, ttl_seconds=2)
        if cached is not None:
            return cached

        latest = self.get_latest()
        _, config_raw, run = self._load_run_context()
        demo_status = self.yolo_demo_service.get_status()
        target_node = demo_status.node_name or run.target_node
        focus_pod = demo_status.focus_pod or run.focus_pod
        node_ip = self._resolve_node_ip(target_node)
        gpu_metrics = self._probe_gpu_live_metrics(target_node, node_ip)
        latency_metrics = self._probe_latency_live_metrics(demo_status.run_id or run.run_id)

        current = FanCycleCurrentMetrics(
            gpu_temp_c=gpu_metrics.get("gpu_temp_c", latest.current.gpu_temp_c),
            fan_pct=gpu_metrics.get("fan_pct", latest.current.fan_pct),
            sm_clock_mhz=gpu_metrics.get("sm_clock_mhz", latest.current.sm_clock_mhz),
            gpu_util_pct=gpu_metrics.get("gpu_util_pct", latest.current.gpu_util_pct),
            server_latency_ms=latency_metrics.get("server_latency_ms", latest.current.server_latency_ms),
            e2e_latency_ms=latency_metrics.get("e2e_latency_ms", latest.current.e2e_latency_ms),
        )

        response = FanCycleLiveResponse(
            schema_name="pre6g.experiments.fan_cycle.live.v1",
            generated_at=int(time.time()),
            run=FanCycleRunInfo(
                run_id=config_raw.get("RUN_ID", run.run_id),
                status="live",
                target_node=target_node,
                gpu_name=run.gpu_name,
                workload=run.workload,
                cycles=run.cycles,
                current_cycle=run.current_cycle,
                current_phase=run.current_phase,
                elapsed_seconds=run.elapsed_seconds,
                focus_pod=focus_pod,
                target_url=demo_status.target_url or run.target_url,
            ),
            current=current,
        )
        self.cache.set(cache_key, response)
        return response
