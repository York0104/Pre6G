from typing import Any, Dict, List

from kubernetes import client, config


class K8sAdapter:
    def __init__(self) -> None:
        config.load_kube_config()
        self.core_api = client.CoreV1Api()

    def list_nodes_raw(self) -> List[Dict[str, Any]]:
        result = self.core_api.list_node().to_dict()
        return result["items"]
