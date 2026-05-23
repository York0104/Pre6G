import json
import subprocess
from pathlib import Path


NAMESPACE = "pre6g-system"
LABEL = "app=pre6g-inventory-collector"


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def main():
    pods_raw = run([
        "kubectl",
        "-n",
        NAMESPACE,
        "get",
        "pods",
        "-l",
        LABEL,
        "-o",
        "json",
    ])
    pods = json.loads(pods_raw)["items"]

    output = {}

    for pod in pods:
        pod_name = pod["metadata"]["name"]
        node_name = pod["spec"]["nodeName"]

        logs = run(["kubectl", "-n", NAMESPACE, "logs", pod_name])
        last_line = logs.strip().splitlines()[-1]
        obj = json.loads(last_line)

        output[node_name] = {
            "cpu": obj.get("cpu", {}),
            "memory": obj.get("memory", {}),
        }

    output_path = Path(__file__).resolve().parents[1] / "data" / "node_inventory_extra.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[INFO] wrote {output_path}")


if __name__ == "__main__":
    main()
