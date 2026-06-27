import unittest

from app.adapters.vllm_workload_adapter import ReplicaMetricSnapshot
from app.services.cache_service import SimpleTTLCache
from app.services.workload_status_service import WorkloadStatusService


def make_pod(
    name: str,
    *,
    owner_kind: str | None,
    owner_name: str | None,
    ready: bool,
    phase: str = "Running",
    namespace: str = "ai-serving",
    node_name: str = "iccl-s3-251230",
) -> dict:
    owner_refs = []
    if owner_kind and owner_name:
        owner_refs.append({"kind": owner_kind, "name": owner_name})
    return {
        "metadata": {
            "name": name,
            "namespace": namespace,
            "ownerReferences": owner_refs,
        },
        "spec": {
            "nodeName": node_name,
            "containers": [
                {
                    "name": "vllm",
                    "ports": [{"name": "http-metrics", "containerPort": 8000}],
                }
            ],
        },
        "status": {
            "phase": phase,
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
        },
    }


def make_deployment(name: str, replicas: int = 1, image: str = "vllm/vllm-openai:v0.23.0") -> dict:
    return {
        "metadata": {"name": name, "namespace": "ai-serving"},
        "spec": {
            "replicas": replicas,
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "vllm",
                            "image": image,
                            "ports": [{"name": "http-metrics", "containerPort": 8000}],
                        }
                    ]
                }
            },
        },
    }


class FakeK8sAdapter:
    def __init__(self, pods: list[dict], deployments: list[dict], replica_sets: dict[tuple[str, str], dict] | None = None):
        self.pods = pods
        self.deployments = deployments
        self.replica_sets = replica_sets or {}

    def list_pods_raw(self, namespace: str | None = None):
        return [pod for pod in self.pods if namespace is None or pod["metadata"]["namespace"] == namespace]

    def list_deployments_raw(self, namespace: str | None = None):
        return [dep for dep in self.deployments if namespace is None or dep["metadata"]["namespace"] == namespace]

    def get_replicaset_raw(self, namespace: str, name: str):
        key = (namespace, name)
        if key not in self.replica_sets:
            raise KeyError(key)
        return self.replica_sets[key]

    def get_deployment_raw(self, namespace: str, name: str):
        for dep in self.deployments:
            if dep["metadata"]["namespace"] == namespace and dep["metadata"]["name"] == name:
                return dep
        raise KeyError((namespace, name))


class FakeVllmAdapter:
    def __init__(self, snapshots: dict[str, ReplicaMetricSnapshot] | None = None):
        self.snapshots = snapshots or {}
        self.query_window_seconds = 10

    def collect_namespace_metrics(self, namespace: str):
        return self.snapshots


class WorkloadStatusServiceTests(unittest.TestCase):
    def test_resolves_replicaset_to_deployment_and_aggregates_metrics(self) -> None:
        pod = make_pod(
            "gemma4-e2b-vllm-abcde",
            owner_kind="ReplicaSet",
            owner_name="gemma4-e2b-vllm-6fdb",
            ready=True,
        )
        rs = {
            "metadata": {
                "name": "gemma4-e2b-vllm-6fdb",
                "namespace": "ai-serving",
                "ownerReferences": [{"kind": "Deployment", "name": "gemma4-e2b-vllm"}],
            }
        }
        metrics = {
            "gemma4-e2b-vllm-abcde": ReplicaMetricSnapshot(
                pod="gemma4-e2b-vllm-abcde",
                namespace="ai-serving",
                node_name="iccl-s3-251230",
                ts=1710000001,
                model_name="gemma4-e2b-w4a16",
                served_model_id="gemma4-e2b-w4a16",
                runtime_version="v0.23.0",
                generation_tokens_per_second=92.4,
                prompt_tokens_per_second=1042.8,
                waiting_requests=2.0,
                kv_cache_usage_percent=71.3,
            )
        }
        service = WorkloadStatusService(
            cache=SimpleTTLCache(),
            k8s_adapter=FakeK8sAdapter(
                pods=[pod],
                deployments=[make_deployment("gemma4-e2b-vllm")],
                replica_sets={("ai-serving", "gemma4-e2b-vllm-6fdb"): rs},
            ),
            vllm_adapter=FakeVllmAdapter(metrics),
        )

        response = service.get_workload_status("ai-serving", "gemma4-e2b-vllm")

        self.assertEqual(response.status, "ready")
        self.assertEqual(response.identity.model_name, "gemma4-e2b-w4a16")
        self.assertEqual(response.identity.runtime_image, "vllm/vllm-openai:v0.23.0")
        self.assertEqual(response.identity.runtime_version, "v0.23.0")
        self.assertEqual(response.replica_summary.desired, 1)
        self.assertEqual(response.replica_summary.ready, 1)
        self.assertEqual(response.replica_summary.metrics_available, 1)
        self.assertEqual(response.replicas[0].owner_resolution, "deployment")
        self.assertEqual(response.replicas[0].pod_phase, "Running")
        self.assertTrue(response.replicas[0].ready_condition)
        self.assertEqual(response.replicas[0].metrics_observed_ts, 1710000001)
        self.assertEqual(response.metrics_observed_ts, 1710000001)
        self.assertAlmostEqual(response.aggregate.generation_tokens_per_second or 0.0, 92.4)
        self.assertAlmostEqual(response.aggregate.kv_cache_usage_percent_max or 0.0, 71.3)

    def test_direct_deployment_ready_but_metrics_missing_is_metrics_unavailable(self) -> None:
        pod = make_pod(
            "gemma4-e2b-vllm-abcde",
            owner_kind="Deployment",
            owner_name="gemma4-e2b-vllm",
            ready=True,
        )
        service = WorkloadStatusService(
            cache=SimpleTTLCache(),
            k8s_adapter=FakeK8sAdapter(
                pods=[pod],
                deployments=[make_deployment("gemma4-e2b-vllm")],
            ),
            vllm_adapter=FakeVllmAdapter(),
        )

        response = service.get_workload_status("ai-serving", "gemma4-e2b-vllm")

        self.assertEqual(response.status, "metrics_unavailable")
        self.assertEqual(response.identity.runtime_image, "vllm/vllm-openai:v0.23.0")
        self.assertEqual(response.replica_summary.ready, 1)
        self.assertEqual(response.replica_summary.metrics_unavailable, 1)
        self.assertEqual(response.replicas[0].pod_phase, "Running")
        self.assertTrue(response.replicas[0].ready_condition)
        self.assertIsNone(response.aggregate.generation_tokens_per_second)

    def test_missing_owner_falls_back_to_pod_name(self) -> None:
        pod = make_pod("orphan-vllm-pod", owner_kind=None, owner_name=None, ready=False, phase="Pending")
        service = WorkloadStatusService(
            cache=SimpleTTLCache(),
            k8s_adapter=FakeK8sAdapter(pods=[pod], deployments=[]),
            vllm_adapter=FakeVllmAdapter(),
        )

        response = service.get_workload_status("ai-serving", "orphan-vllm-pod")

        self.assertEqual(response.status, "not_ready")
        self.assertEqual(response.replicas[0].owner_resolution, "fallback")
        self.assertEqual(response.replicas[0].pod_phase, "Pending")
        self.assertFalse(response.replicas[0].ready_condition)
        self.assertEqual(response.replica_summary.ready, 0)

    def test_replicaset_lookup_failure_returns_partial_owner_resolution(self) -> None:
        pod = make_pod(
            "gemma4-e2b-vllm-abcde",
            owner_kind="ReplicaSet",
            owner_name="gemma4-e2b-vllm-6fdb",
            ready=False,
            phase="CrashLoopBackOff",
        )
        service = WorkloadStatusService(
            cache=SimpleTTLCache(),
            k8s_adapter=FakeK8sAdapter(
                pods=[pod],
                deployments=[make_deployment("gemma4-e2b-vllm")],
                replica_sets={},
            ),
            vllm_adapter=FakeVllmAdapter(),
        )

        response = service.get_workload_status("ai-serving", "gemma4-e2b-vllm-6fdb")

        self.assertEqual(response.status, "not_ready")
        self.assertEqual(response.replicas[0].owner_resolution, "partial")


if __name__ == "__main__":
    unittest.main()
