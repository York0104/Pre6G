from typing import Any, Dict, List

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException


class K8sAdapter:
    def __init__(self) -> None:
        try:
            config.load_incluster_config()
        except ConfigException:
            config.load_kube_config()
        self.core_api = client.CoreV1Api()
        self.apps_api = client.AppsV1Api()

    def list_nodes_raw(self) -> List[Dict[str, Any]]:
        result = self.core_api.list_node().to_dict()
        return result["items"]

    def list_pods_raw(self, namespace: str | None = None) -> List[Dict[str, Any]]:
        if namespace:
            result = self.core_api.list_namespaced_pod(namespace).to_dict()
        else:
            result = self.core_api.list_pod_for_all_namespaces().to_dict()
        return result["items"]

    def get_pod_raw(self, namespace: str, pod_name: str) -> Dict[str, Any]:
        return self.core_api.read_namespaced_pod(name=pod_name, namespace=namespace).to_dict()

    def list_deployments_raw(self, namespace: str | None = None) -> List[Dict[str, Any]]:
        if namespace:
            result = self.apps_api.list_namespaced_deployment(namespace).to_dict()
        else:
            result = self.apps_api.list_deployment_for_all_namespaces().to_dict()
        return result["items"]

    def get_deployment_raw(self, namespace: str, name: str) -> Dict[str, Any]:
        return self.apps_api.read_namespaced_deployment(name=name, namespace=namespace).to_dict()

    def get_replicaset_raw(self, namespace: str, name: str) -> Dict[str, Any]:
        return self.apps_api.read_namespaced_replica_set(name=name, namespace=namespace).to_dict()
