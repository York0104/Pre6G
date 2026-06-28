import json
import os
import signal
import subprocess
import time
from pathlib import Path

from app.schemas.experiment import FanCycleExecutionStatusResponse
from app.services.experiment_runtime import AUTOSCALE_API_ROOT
from app.services.experiment_runtime import REPO_ROOT
from app.services.experiment_runtime import load_experiment_runtime_config

RUNTIME_ROOT = AUTOSCALE_API_ROOT / "runtime" / "fan_cycle"
STATE_PATH = RUNTIME_ROOT / "state.json"


def _now_epoch() -> int:
    return int(time.time())


def _ensure_dirs() -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _default_state() -> dict:
    config = load_experiment_runtime_config()
    return {
        "status": "idle",
        "run_id": "",
        "pid": 0,
        "started_at": 0,
        "stdout_log": "",
        "stderr_log": "",
        "exit_code_file": "",
        "result_run_dir": "",
        "message": "Fan-cycle experiment is idle",
        "last_exit_code": None,
        "namespace": config.namespace,
        "focus_deploy": config.focus_deploy,
        "bg_deploy": config.bg_deploy,
        "node_name": config.node_name,
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


class FanCycleRunService:
    def __init__(self) -> None:
        self.config = load_experiment_runtime_config()

    def _latest_run_dir_since(self, started_at: int) -> str:
        results_root = self.config.fan_cycle_results_root
        if not results_root.exists():
            return ""
        candidates = sorted(
            [p for p in results_root.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            if int(candidate.stat().st_mtime) + 5 >= started_at:
                return str(candidate)
        return ""

    def _refresh_state(self) -> dict:
        state = _read_state()
        pid = int(state.get("pid", 0))
        if state.get("status") in {"starting", "running", "stopping"} and not _pid_alive(pid):
            exit_code = None
            exit_code_file = state.get("exit_code_file", "")
            if exit_code_file and Path(exit_code_file).exists():
                content = Path(exit_code_file).read_text(encoding="utf-8").strip()
                if content:
                    try:
                        exit_code = int(content)
                    except ValueError:
                        exit_code = None

            result_run_dir = state.get("result_run_dir", "") or self._latest_run_dir_since(
                int(state.get("started_at", 0))
            )
            state["result_run_dir"] = result_run_dir
            state["pid"] = 0
            state["last_exit_code"] = exit_code
            if exit_code in (0, None):
                state["status"] = "stopped"
                state["message"] = "Fan-cycle experiment finished"
            else:
                state["status"] = "error"
                state["message"] = f"Fan-cycle experiment exited with code {exit_code}"
            _write_state(state)

        if state.get("status") == "running" and not state.get("result_run_dir"):
            state["result_run_dir"] = self._latest_run_dir_since(int(state.get("started_at", 0)))
            _write_state(state)
        return state

    def _status_response(self, state: dict) -> FanCycleExecutionStatusResponse:
        return FanCycleExecutionStatusResponse(
            schema_name="pre6g.experiments.fan_cycle.execution_status.v1",
            generated_at=_now_epoch(),
            status=state.get("status", "idle"),
            run_id=state.get("run_id", ""),
            pid=int(state.get("pid", 0)),
            started_at=int(state.get("started_at", 0)),
            result_run_dir=state.get("result_run_dir", ""),
            stdout_log=state.get("stdout_log", ""),
            stderr_log=state.get("stderr_log", ""),
            namespace=state.get("namespace", self.config.namespace),
            focus_deploy=state.get("focus_deploy", self.config.focus_deploy),
            bg_deploy=state.get("bg_deploy", self.config.bg_deploy),
            node_name=state.get("node_name", self.config.node_name),
            message=state.get("message", ""),
            last_exit_code=state.get("last_exit_code"),
        )

    def get_status(self) -> FanCycleExecutionStatusResponse:
        return self._status_response(self._refresh_state())

    def start(self) -> FanCycleExecutionStatusResponse:
        state = self._refresh_state()
        if state.get("status") in {"starting", "running"}:
            return self._status_response(state)

        _ensure_dirs()
        runtime_run_id = f"fan_cycle_runtime_{time.strftime('%Y%m%d_%H%M%S')}"
        run_dir = RUNTIME_ROOT / runtime_run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        stdout_log = run_dir / "runner_stdout.log"
        stderr_log = run_dir / "runner_stderr.log"
        exit_code_file = run_dir / "runner_exit_code.txt"

        command = (
            f"cd {REPO_ROOT} && "
            f"bash {self.config.fan_cycle_runner} ; "
            f"rc=$?; "
            f"printf '%s' \"$rc\" > {exit_code_file}; "
            "exit \"$rc\""
        )

        env = os.environ.copy()
        env.update(self.config.fan_cycle_runner_env())

        stdout_fh = stdout_log.open("w", encoding="utf-8")
        stderr_fh = stderr_log.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            ["bash", "-lc", command],
            cwd=REPO_ROOT,
            env=env,
            stdout=stdout_fh,
            stderr=stderr_fh,
            start_new_session=True,
        )
        stdout_fh.close()
        stderr_fh.close()

        state = {
            "status": "running",
            "run_id": runtime_run_id,
            "pid": proc.pid,
            "started_at": _now_epoch(),
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
            "exit_code_file": str(exit_code_file),
            "result_run_dir": "",
            "message": "Fan-cycle experiment is running",
            "last_exit_code": None,
            "namespace": self.config.namespace,
            "focus_deploy": self.config.focus_deploy,
            "bg_deploy": self.config.bg_deploy,
            "node_name": self.config.node_name,
        }
        _write_state(state)
        return self._status_response(state)

    def stop(self) -> FanCycleExecutionStatusResponse:
        state = self._refresh_state()
        pid = int(state.get("pid", 0))
        if pid and _pid_alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                state["status"] = "stopping"
                state["message"] = "Stopping fan-cycle experiment"
                _write_state(state)
            except OSError:
                state["status"] = "error"
                state["message"] = "Failed to stop fan-cycle experiment process"
                _write_state(state)
        else:
            state["status"] = "stopped"
            state["pid"] = 0
            state["message"] = "Fan-cycle experiment is not running"
            _write_state(state)
        return self._status_response(state)
