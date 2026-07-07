#!/usr/bin/env python3

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
ENV_PATH = ROOT / "autoscale-source-split" / "01-monitoring-layer" / "systemd" / "autoscale-api.env"
ENV_EXAMPLE_PATH = ROOT / "autoscale-source-split" / "01-monitoring-layer" / "systemd" / "autoscale-api.env.example"
NAMESPACE = "pre6g-dashboard"
CONFIGMAP_NAME = "autoscale-api-config"
SECRET_NAME = "autoscale-api-secret"
SECRET_KEYS = {"AUTOSCALE_API_TOKEN", "PRE6G_EXPERIMENT_CC_PASSWORD", "YOLO_DEMO_CC_PASSWORD"}


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def kubectl_json(args: list[str]) -> dict:
    output = subprocess.check_output(["kubectl", *args], text=True)
    return json.loads(output)


def kubectl_apply(payload: dict) -> None:
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=json.dumps(payload),
        text=True,
        check=True,
    )


def main() -> None:
    values = read_env_file(ENV_EXAMPLE_PATH)
    if ENV_PATH.exists():
        values.update(read_env_file(ENV_PATH))
    config_updates = {key: value for key, value in values.items() if key not in SECRET_KEYS}

    configmap = kubectl_json(["-n", NAMESPACE, "get", "configmap", CONFIGMAP_NAME, "-o", "json"])
    config_data = dict(configmap.get("data") or {})
    config_data.update(config_updates)

    kubectl_apply(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": CONFIGMAP_NAME, "namespace": NAMESPACE},
            "data": config_data,
        }
    )

    secret_patch = {
        "stringData": {
            key: value
            for key, value in values.items()
            if key in {"AUTOSCALE_API_TOKEN", "PRE6G_EXPERIMENT_CC_PASSWORD"} and value
        }
    }
    if secret_patch["stringData"]:
        subprocess.run(
            [
                "kubectl",
                "-n",
                NAMESPACE,
                "patch",
                "secret",
                SECRET_NAME,
                "--type",
                "merge",
                "-p",
                json.dumps(secret_patch),
            ],
            check=True,
        )

    subprocess.run(["kubectl", "-n", NAMESPACE, "rollout", "restart", "deploy/autoscale-api"], check=True)
    subprocess.run(
        ["kubectl", "-n", NAMESPACE, "rollout", "status", "deploy/autoscale-api", "--timeout=180s"],
        check=True,
    )
    print("live autoscale-api config synced")


if __name__ == "__main__":
    main()
