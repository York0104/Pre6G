import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Literal

from app.schemas.experiment import (
    YoloDemoEvent,
    YoloDemoEventsResponse,
    YoloDemoStatusResponse,
)

AUTOSCALE_ROOT = Path(__file__).resolve().parents[3]
YOLO_DEMO_ROOT = AUTOSCALE_ROOT / "experiments" / "experiments_yolo" / "yolo_demo"
RUNTIME_ROOT = YOLO_DEMO_ROOT / "runtime"
RUNS_ROOT = RUNTIME_ROOT / "runs"
STATE_PATH = RUNTIME_ROOT / "state.json"
EVENTS_PATH = RUNTIME_ROOT / "events.jsonl"
REQUEST_CLIENT = (
    AUTOSCALE_ROOT / "experiments" / "experiments_yolo" / "common" / "request_client_serial.py"
)
SANITY_IMAGE = AUTOSCALE_ROOT / "experiments" / "yolo26_workload" / "test_images" / "sanity_input.png"

NAMESPACE = "intent-lab"
FOCUS_DEPLOY = "yolo26n-task3-focus"
BG_DEPLOY = "yolo26n-task3-bg"
MEAS_SVC_NAME = "yolo26n-task3"
NODE_NAME = "icclz1"
NODE_SSH = "icclz1@100.105.48.97"
WORKER_REPO = "/home/icclz1/gpu-tempctl-lab"
WORKER_VENV = "/home/icclz1/gpu-tempctl-1080ti/bin/activate"
DEFAULT_REPEAT = 10
DEFAULT_TIMEOUT_SEC = 30
DEFAULT_DURATION_SEC = 86400
DEFAULT_BG_SIZE = 4096
DEFAULT_BG_DUTY = 1.0
DEFAULT_BG_PERIOD_MS = 100
CC_PASSWORD = os.getenv("YOLO_DEMO_CC_PASSWORD", "nctuiiot")
STARTUP_GRACE_SECONDS = 20

FanMode = Literal["GPU_DEFAULT", "FIXED_5", "FIXED_15", "FIXED_20", "FIXED_25"]
VALID_FAN_MODES: tuple[FanMode, ...] = (
    "GPU_DEFAULT",
    "FIXED_5",
    "FIXED_15",
    "FIXED_20",
    "FIXED_25",
)


def _run_command(args: list[str], timeout: float = 30.0) -> str:
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return completed.stdout.strip()


def _ensure_dirs() -> None:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)


def _now_epoch() -> int:
    return int(time.time())


def _default_state() -> dict:
    return {
        "status": "idle",
        "run_id": "",
        "namespace": NAMESPACE,
        "focus_deploy": FOCUS_DEPLOY,
        "bg_deploy": BG_DEPLOY,
        "focus_pod": "",
        "target_url": "",
        "target_mode": "",
        "node_name": NODE_NAME,
        "measurement_pid": 0,
        "bgload_pid": 0,
        "fan_mode": "GPU_DEFAULT",
        "started_at": 0,
        "message": "YOLO demo is idle",
    }


def _read_state() -> dict:
    _ensure_dirs()
    if not STATE_PATH.exists():
        state = _default_state()
        STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _write_state(state: dict) -> None:
    _ensure_dirs()
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _append_event(level: str, event: str, message: str) -> None:
    _ensure_dirs()
    row = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "level": level,
        "event": event,
        "message": message,
    }
    with EVENTS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_events(limit: int = 50) -> list[dict]:
    _ensure_dirs()
    if not EVENTS_PATH.exists():
        return []
    rows = [
        json.loads(line)
        for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return rows[-limit:]


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class YoloDemoService:
    def _refresh_state(self) -> dict:
        state = _read_state()
        measurement_alive = _pid_alive(int(state.get("measurement_pid", 0)))
        bgload_alive = self._remote_bgload_alive(int(state.get("bgload_pid", 0)))

        if state["status"] in {"running", "starting"}:
            if measurement_alive or bgload_alive:
                state["status"] = "running"
                state["message"] = "YOLO demo is running"
            elif (
                state["status"] == "starting"
                and (_now_epoch() - int(state.get("started_at", 0))) < STARTUP_GRACE_SECONDS
            ):
                state["message"] = "YOLO demo is still starting"
            else:
                state["status"] = "stopped"
                state["message"] = "YOLO demo processes have exited"
                state["measurement_pid"] = 0
                state["bgload_pid"] = 0
                _append_event("warn", "demo_exited", "YOLO demo processes exited unexpectedly")
            _write_state(state)
        return state

    def _state_response(self, state: dict) -> YoloDemoStatusResponse:
        return YoloDemoStatusResponse(
            schema_name="pre6g.experiments.yolo_demo.status.v1",
            generated_at=_now_epoch(),
            status=state["status"],
            run_id=state.get("run_id", ""),
            namespace=state.get("namespace", NAMESPACE),
            focus_deploy=state.get("focus_deploy", FOCUS_DEPLOY),
            bg_deploy=state.get("bg_deploy", BG_DEPLOY),
            focus_pod=state.get("focus_pod", ""),
            target_url=state.get("target_url", ""),
            target_mode=state.get("target_mode", ""),
            node_name=state.get("node_name", NODE_NAME),
            measurement_pid=int(state.get("measurement_pid", 0)),
            bgload_pid=int(state.get("bgload_pid", 0)),
            fan_mode=state.get("fan_mode", "GPU_DEFAULT"),
            started_at=int(state.get("started_at", 0)),
            message=state.get("message", ""),
        )

    def get_status(self) -> YoloDemoStatusResponse:
        return self._state_response(self._refresh_state())

    def get_events(self) -> YoloDemoEventsResponse:
        events = [
            YoloDemoEvent(
                time=row.get("time", ""),
                level=row.get("level", "info"),
                event=row.get("event", ""),
                message=row.get("message", ""),
            )
            for row in _read_events()
        ]
        return YoloDemoEventsResponse(
            schema_name="pre6g.experiments.yolo_demo.events.v1",
            generated_at=_now_epoch(),
            events=events,
        )

    def _resolve_target(self) -> tuple[str, str, str]:
        focus_pod = _run_command(
            [
                "kubectl",
                "-n",
                NAMESPACE,
                "get",
                "pod",
                "-l",
                "app=yolo26n,role=focus",
                "-o",
                "jsonpath={.items[0].metadata.name}",
            ],
            timeout=10.0,
        )
        focus_ip = _run_command(
            [
                "kubectl",
                "-n",
                NAMESPACE,
                "get",
                "pod",
                "-l",
                "app=yolo26n,role=focus",
                "-o",
                "jsonpath={.items[0].status.podIP}",
            ],
            timeout=10.0,
        )
        meas_svc_ip = _run_command(
            [
                "kubectl",
                "-n",
                NAMESPACE,
                "get",
                "svc",
                MEAS_SVC_NAME,
                "-o",
                "jsonpath={.spec.clusterIP}",
            ],
            timeout=10.0,
        )
        if meas_svc_ip:
            return focus_pod, f"http://{meas_svc_ip}:18080/infer?repeat={DEFAULT_REPEAT}", "service"
        return focus_pod, f"http://{focus_ip}:18080/infer?repeat={DEFAULT_REPEAT}", "pod"

    def _remote_bgload_alive(self, pid: int) -> bool:
        if not pid:
            return False
        try:
            _run_command(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-o",
                    "ConnectTimeout=5",
                    NODE_SSH,
                    f"kill -0 {pid}",
                ],
                timeout=8.0,
            )
            return True
        except Exception:
            return False

    def _start_remote_bgload(self, run_id: str) -> int:
        remote_stdout = f"/tmp/{run_id}_bgload_stdout.log"
        remote_stderr = f"/tmp/{run_id}_bgload_stderr.log"
        remote_cmd = f"""bash -lc 'cd {WORKER_REPO} && source {WORKER_VENV} && source fan_control_lab/env.sh && export MPLCONFIGDIR=/tmp/mpl-yolo-demo && mkdir -p /tmp/mpl-yolo-demo && python3 - <<\"PY\"
import subprocess
cmd = ["python", "fan_control_lab/gpu_load_torch.py", "--seconds", "{DEFAULT_DURATION_SEC}", "--size", "{DEFAULT_BG_SIZE}", "--duty", "{DEFAULT_BG_DUTY}", "--period-ms", "{DEFAULT_BG_PERIOD_MS}"]
with open("{remote_stdout}", "w", encoding="utf-8") as out, open("{remote_stderr}", "w", encoding="utf-8") as err:
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
    print(p.pid)
PY'"""
        output = _run_command(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "ConnectTimeout=5",
                NODE_SSH,
                remote_cmd,
            ],
            timeout=20.0,
        )
        return int(output.splitlines()[-1].strip())

    def _stop_remote_bgload(self, pid: int) -> None:
        if not pid:
            return
        try:
            _run_command(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-o",
                    "ConnectTimeout=5",
                    NODE_SSH,
                    f"kill -TERM {pid} >/dev/null 2>&1 || true",
                ],
                timeout=8.0,
            )
        except Exception:
            pass

    def _stop_all_remote_bgloads(self) -> None:
        try:
            _run_command(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-o",
                    "ConnectTimeout=5",
                    NODE_SSH,
                    "pkill -f 'fan_control_lab/gpu_load_torch.py' >/dev/null 2>&1 || true",
                ],
                timeout=10.0,
            )
        except Exception:
            pass

    def _apply_fan_mode_remote(self, mode: FanMode) -> None:
        if mode == "GPU_DEFAULT":
            remote_cmd = (
                f"bash -lc 'cd {WORKER_REPO} "
                f"&& source {WORKER_VENV} "
                f"&& python fan_control_lab/cc.py -p {CC_PASSWORD} --mode GPU_DEFAULT'"
            )
        else:
            pct = int(mode.split("_")[1])
            remote_cmd = (
                f"bash -lc 'cd {WORKER_REPO} "
                f"&& source {WORKER_VENV} "
                f"&& python fan_control_lab/cc.py -p {CC_PASSWORD} -m NVIDIA -c fan --speed {pct}'"
            )
        _run_command(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "ConnectTimeout=5",
                NODE_SSH,
                remote_cmd,
            ],
            timeout=15.0,
        )

    def apply_fan_mode(self, mode: FanMode) -> YoloDemoStatusResponse:
        if mode not in VALID_FAN_MODES:
            raise ValueError(f"Unsupported fan mode: {mode}")
        self._apply_fan_mode_remote(mode)
        state = _read_state()
        state["fan_mode"] = mode
        state["message"] = f"Applied fan mode {mode}"
        _write_state(state)
        _append_event("info", "fan_mode_applied", f"Fan mode set to {mode}")
        return self._state_response(state)

    def start(self) -> YoloDemoStatusResponse:
        state = self._refresh_state()
        if state["status"] == "running":
            return self._state_response(state)

        run_id = f"yolo_demo_{time.strftime('%Y%m%d_%H%M%S')}"
        run_dir = RUNS_ROOT / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        state.update(
            {
                "status": "starting",
                "run_id": run_id,
                "started_at": _now_epoch(),
                "message": "Preparing YOLO demo workload",
            }
        )
        _write_state(state)
        _append_event("info", "demo_start_requested", f"Starting YOLO demo run {run_id}")

        measurement_proc = None
        bgload_pid = 0
        try:
            _run_command(
                ["kubectl", "-n", NAMESPACE, "scale", f"deploy/{FOCUS_DEPLOY}", "--replicas=1"],
                timeout=20.0,
            )
            _append_event("info", "focus_scaled", f"Scaled {FOCUS_DEPLOY} to 1 replica")
            _run_command(
                ["kubectl", "-n", NAMESPACE, "scale", f"deploy/{BG_DEPLOY}", "--replicas=0"],
                timeout=20.0,
            )
            _append_event("info", "bg_scaled", f"Scaled {BG_DEPLOY} to 0 replicas")
            _run_command(
                ["kubectl", "-n", NAMESPACE, "rollout", "status", f"deploy/{FOCUS_DEPLOY}", "--timeout=180s"],
                timeout=190.0,
            )
            _append_event("info", "focus_ready", f"{FOCUS_DEPLOY} rollout completed")

            focus_pod, target_url, target_mode = self._resolve_target()
            _append_event("info", "focus_pod_resolved", f"Resolved focus pod {focus_pod}")
            _append_event("info", "target_url_resolved", f"Resolved target URL via {target_mode} mode")

            bgload_pid = self._start_remote_bgload(run_id)
            _append_event("info", "bgload_started", f"Started GPU background load pid={bgload_pid}")

            measurement_stdout = (run_dir / "measurement_stdout.log").open("w", encoding="utf-8")
            measurement_stderr = (run_dir / "measurement_stderr.log").open("w", encoding="utf-8")
            measurement_cmd = [
                "bash",
                "-lc",
                (
                    f"cd {AUTOSCALE_ROOT} && "
                    "source iccl/bin/activate && "
                    f"python3 {REQUEST_CLIENT} "
                    "--role measurement "
                    f"--url '{target_url}' "
                    f"--image {SANITY_IMAGE} "
                    f"--duration {DEFAULT_DURATION_SEC} "
                    f"--timeout {DEFAULT_TIMEOUT_SEC} "
                    f"--output {run_dir / 'measurement_raw.csv'}"
                ),
            ]
            measurement_proc = subprocess.Popen(
                measurement_cmd,
                stdout=measurement_stdout,
                stderr=measurement_stderr,
                cwd=AUTOSCALE_ROOT,
                start_new_session=True,
            )
            _append_event("info", "serial_client_started", f"Started serial request client pid={measurement_proc.pid}")

            state.update(
                {
                    "status": "running",
                    "focus_pod": focus_pod,
                    "target_url": target_url,
                    "target_mode": target_mode,
                    "measurement_pid": measurement_proc.pid,
                    "bgload_pid": bgload_pid,
                    "message": "YOLO demo is running",
                }
            )
            _write_state(state)
            _append_event("info", "demo_running", "YOLO demo is now running")
            return self._state_response(state)
        except Exception:
            if measurement_proc is not None:
                try:
                    os.killpg(os.getpgid(measurement_proc.pid), signal.SIGTERM)
                except OSError:
                    pass
            if bgload_pid:
                self._stop_remote_bgload(bgload_pid)
            state.update(
                {
                    "status": "error",
                    "measurement_pid": 0,
                    "bgload_pid": 0,
                    "focus_pod": "",
                    "target_url": "",
                    "target_mode": "",
                    "message": "YOLO demo failed to start",
                }
            )
            _write_state(state)
            raise

    def stop(self) -> YoloDemoStatusResponse:
        state = _read_state()
        state["status"] = "stopping"
        state["message"] = "Stopping YOLO demo workload"
        _write_state(state)
        _append_event("warn", "demo_stop_requested", "Stopping YOLO demo")

        measurement_pid = int(state.get("measurement_pid", 0))
        if measurement_pid and _pid_alive(measurement_pid):
            try:
                os.killpg(os.getpgid(measurement_pid), signal.SIGTERM)
                _append_event("warn", "serial_client_stopped", f"Stopped serial request client pid={measurement_pid}")
            except OSError:
                pass

        self._stop_remote_bgload(int(state.get("bgload_pid", 0)))
        self._stop_all_remote_bgloads()
        if int(state.get("bgload_pid", 0)):
            _append_event("warn", "bgload_stopped", f"Stopped GPU background load pid={state.get('bgload_pid', 0)}")

        try:
            _run_command(
                ["kubectl", "-n", NAMESPACE, "scale", f"deploy/{FOCUS_DEPLOY}", "--replicas=0"],
                timeout=20.0,
            )
            _append_event("warn", "focus_scaled_down", f"Scaled {FOCUS_DEPLOY} to 0 replicas")
        except Exception:
            pass
        try:
            _run_command(
                ["kubectl", "-n", NAMESPACE, "scale", f"deploy/{BG_DEPLOY}", "--replicas=0"],
                timeout=20.0,
            )
            _append_event("warn", "bg_scaled_down", f"Scaled {BG_DEPLOY} to 0 replicas")
        except Exception:
            pass

        state.update(
            {
                "status": "stopped",
                "measurement_pid": 0,
                "bgload_pid": 0,
                "focus_pod": "",
                "target_url": "",
                "target_mode": "",
                "message": "YOLO demo stopped and services scaled down",
            }
        )
        _write_state(state)
        _append_event("info", "demo_stopped", "YOLO demo stopped and services scaled down")
        return self._state_response(state)
