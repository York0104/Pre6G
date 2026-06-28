import os
from dataclasses import dataclass
from pathlib import Path


SERVICE_FILE = Path(__file__).resolve()
REPO_ROOT = SERVICE_FILE.parents[5]
EXPERIMENT_LAYER_ROOT = REPO_ROOT / "autoscale-source-split" / "02-experiment-layer"
SHARED_API_ROOT = REPO_ROOT / "autoscale-source-split" / "03-shared-api-dashboard"
AUTOSCALE_API_ROOT = SHARED_API_ROOT / "autoscale_api"


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


@dataclass(frozen=True)
class ExperimentRuntimeConfig:
    namespace: str
    node_name: str
    node_ssh: str
    focus_deploy: str
    bg_deploy: str
    meas_svc_name: str
    target_mode: str
    worker_repo: str
    worker_venv: str
    cc_password: str
    default_repeat: int
    default_timeout_sec: int
    default_duration_sec: int
    default_bg_size: int
    default_bg_duty: float
    default_bg_period_ms: int
    runner_cycles: int
    runner_normal_hold_seconds: int
    runner_fault_hold_seconds: int
    runner_recovery_stable_seconds: int
    runner_recovery_max_seconds: int
    runner_workload_headroom_seconds: int
    runner_fixed_fan_pct: int
    runner_vm_agg_interval: float
    vm_url: str
    netdata_url: str
    netdata_child_url: str
    netdata_parent_base_url: str

    @property
    def request_client(self) -> Path:
        return EXPERIMENT_LAYER_ROOT / "experiments_yolo" / "common" / "request_client_serial.py"

    @property
    def sanity_image(self) -> Path:
        return EXPERIMENT_LAYER_ROOT / "yolo26_workload" / "test_images" / "sanity_input.png"

    @property
    def yolo_demo_runtime_root(self) -> Path:
        return EXPERIMENT_LAYER_ROOT / "experiments_yolo" / "yolo_demo" / "runtime"

    @property
    def fan_cycle_results_root(self) -> Path:
        return EXPERIMENT_LAYER_ROOT / "experiments_yolo" / "results" / "single_pod_bgload_fan_cycle"

    @property
    def fan_cycle_runner(self) -> Path:
        return (
            EXPERIMENT_LAYER_ROOT
            / "experiments_yolo"
            / "single_pod_bgload_fan_cycle"
            / "run_single_pod_bgload_fan_cycle.sh"
        )

    def fan_cycle_runner_env(self) -> dict[str, str]:
        env = {
            "NAMESPACE": self.namespace,
            "NODE_NAME": self.node_name,
            "NODE_SSH": self.node_ssh,
            "FOCUS_DEPLOY": self.focus_deploy,
            "BG_DEPLOY_1": self.bg_deploy,
            "TARGET_MODE": self.target_mode,
            "TIMEOUT_SEC": str(self.default_timeout_sec),
            "REPEAT": str(self.default_repeat),
            "CYCLES": str(self.runner_cycles),
            "NORMAL_HOLD_SECONDS": str(self.runner_normal_hold_seconds),
            "FAULT_HOLD_SECONDS": str(self.runner_fault_hold_seconds),
            "RECOVERY_STABLE_SECONDS": str(self.runner_recovery_stable_seconds),
            "RECOVERY_MAX_SECONDS": str(self.runner_recovery_max_seconds),
            "FIXED_FAN_PCT": str(self.runner_fixed_fan_pct),
            "BG_SIZE": str(self.default_bg_size),
            "BG_DUTY": str(self.default_bg_duty),
            "BG_PERIOD_MS": str(self.default_bg_period_ms),
            "WORKLOAD_HEADROOM_SECONDS": str(self.runner_workload_headroom_seconds),
            "VM_AGG_INTERVAL": str(self.runner_vm_agg_interval),
            "VM_URL": self.vm_url,
            "NETDATA_URL": self.netdata_url,
            "NETDATA_CHILD_URL": self.netdata_child_url,
            "NETDATA_PARENT_BASE_URL": self.netdata_parent_base_url,
        }
        if self.meas_svc_name:
            env["MEAS_SVC_NAME"] = self.meas_svc_name
        if self.cc_password:
            env["CC_PASSWORD"] = self.cc_password
        return env


def load_experiment_runtime_config() -> ExperimentRuntimeConfig:
    return ExperimentRuntimeConfig(
        namespace=_env("PRE6G_EXPERIMENT_NAMESPACE", "intent-lab"),
        node_name=_env("PRE6G_EXPERIMENT_NODE_NAME", "icclz1"),
        node_ssh=_env("PRE6G_EXPERIMENT_NODE_SSH", "icclz1-gpu"),
        focus_deploy=_env("PRE6G_EXPERIMENT_FOCUS_DEPLOY", "yolo26n-focus"),
        bg_deploy=_env("PRE6G_EXPERIMENT_BG_DEPLOY", "yolo26n-bg-1"),
        meas_svc_name=_env("PRE6G_EXPERIMENT_MEAS_SVC_NAME", ""),
        target_mode=_env("PRE6G_EXPERIMENT_TARGET_MODE", "pod"),
        worker_repo=_env("PRE6G_EXPERIMENT_WORKER_REPO", "/home/icclz1/gpu-tempctl-lab"),
        worker_venv=_env("PRE6G_EXPERIMENT_WORKER_VENV", "/home/icclz1/gpu-tempctl-1080ti/bin/activate"),
        cc_password=_env("PRE6G_EXPERIMENT_CC_PASSWORD", _env("YOLO_DEMO_CC_PASSWORD", "")),
        default_repeat=int(_env("PRE6G_EXPERIMENT_REPEAT", "10") or "10"),
        default_timeout_sec=int(_env("PRE6G_EXPERIMENT_TIMEOUT_SEC", "30") or "30"),
        default_duration_sec=int(_env("PRE6G_EXPERIMENT_DURATION_SEC", "86400") or "86400"),
        default_bg_size=int(_env("PRE6G_EXPERIMENT_BG_SIZE", "4096") or "4096"),
        default_bg_duty=float(_env("PRE6G_EXPERIMENT_BG_DUTY", "1.0") or "1.0"),
        default_bg_period_ms=int(_env("PRE6G_EXPERIMENT_BG_PERIOD_MS", "100") or "100"),
        runner_cycles=int(_env("PRE6G_EXPERIMENT_CYCLES", "1") or "1"),
        runner_normal_hold_seconds=int(_env("PRE6G_EXPERIMENT_NORMAL_HOLD_SECONDS", "300") or "300"),
        runner_fault_hold_seconds=int(_env("PRE6G_EXPERIMENT_FAULT_HOLD_SECONDS", "300") or "300"),
        runner_recovery_stable_seconds=int(
            _env("PRE6G_EXPERIMENT_RECOVERY_STABLE_SECONDS", "60") or "60"
        ),
        runner_recovery_max_seconds=int(_env("PRE6G_EXPERIMENT_RECOVERY_MAX_SECONDS", "300") or "300"),
        runner_workload_headroom_seconds=int(
            _env("PRE6G_EXPERIMENT_WORKLOAD_HEADROOM_SECONDS", "120") or "120"
        ),
        runner_fixed_fan_pct=int(_env("PRE6G_EXPERIMENT_FIXED_FAN_PCT", "5") or "5"),
        runner_vm_agg_interval=float(_env("PRE6G_EXPERIMENT_VM_AGG_INTERVAL", "1.0") or "1.0"),
        vm_url=_env("VM_URL", "http://140.113.179.9:31888"),
        netdata_url=_env("NETDATA_URL", "http://140.113.179.9:32163"),
        netdata_child_url=_env("NETDATA_CHILD_URL", _env("NETDATA_URL", "http://140.113.179.9:32163")),
        netdata_parent_base_url=_env(
            "NETDATA_PARENT_BASE_URL",
            _env("NETDATA_URL", "http://140.113.179.9:32163"),
        ),
    )
