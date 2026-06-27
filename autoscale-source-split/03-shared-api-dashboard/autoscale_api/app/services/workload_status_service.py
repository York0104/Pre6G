import os
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from app.adapters.k8s_adapter import K8sAdapter
from app.adapters.vllm_workload_adapter import (
    ReplicaMetricSnapshot,
    VllmWorkloadAdapter,
)
from app.schemas.workload import (
    WorkloadAggregateMetrics,
    WorkloadIdentity,
    WorkloadListItem,
    WorkloadListResponse,
    WorkloadReplicaStatus,
    WorkloadReplicaSummary,
    WorkloadStatusResponse,
)
from app.services.cache_service import SimpleTTLCache


@dataclass
class _ResolvedOwner:
    workload: str
    owner_resolution: str


class WorkloadStatusService:
    def __init__(
        self,
        cache: SimpleTTLCache | None = None,
        k8s_adapter: K8sAdapter | None = None,
        vllm_adapter: VllmWorkloadAdapter | None = None,
    ) -> None:
        self.cache = cache or SimpleTTLCache()
        self.k8s = k8s_adapter or K8sAdapter()
        self.vllm = vllm_adapter or VllmWorkloadAdapter()
        self.default_namespace = os.getenv("PRE6G_WORKLOAD_NAMESPACE", "ai-serving").strip() or "ai-serving"
        self.query_window_seconds = self.vllm.query_window_seconds

    @staticmethod
    def _is_pod_ready(pod: dict) -> bool:
        conditions = pod.get("status", {}).get("conditions") or []
        for condition in conditions:
            if condition.get("type") == "Ready":
                return condition.get("status") == "True"
        return False

    @staticmethod
    def _pod_phase(pod: dict) -> str:
        return str(pod.get("status", {}).get("phase") or "").strip()

    @staticmethod
    def _pod_node_name(pod: dict) -> str:
        return str(pod.get("spec", {}).get("node_name") or pod.get("spec", {}).get("nodeName") or "")

    @staticmethod
    def _deployment_desired_replicas(deployment: dict) -> int:
        spec = deployment.get("spec") or {}
        replicas = spec.get("replicas")
        if replicas is None:
            return 1
        return int(replicas)

    @staticmethod
    def _replica_has_metrics(replica: WorkloadReplicaStatus) -> bool:
        return any(
            value is not None
            for value in (
                replica.generation_tokens_per_second,
                replica.prompt_tokens_per_second,
                replica.waiting_requests,
                replica.kv_cache_usage_percent,
            )
        )

    @staticmethod
    def _sum(values: Iterable[Optional[float]]) -> Optional[float]:
        filtered = [float(v) for v in values if v is not None]
        if not filtered:
            return None
        return sum(filtered)

    @staticmethod
    def _max(values: Iterable[Optional[float]]) -> Optional[float]:
        filtered = [float(v) for v in values if v is not None]
        if not filtered:
            return None
        return max(filtered)

    @staticmethod
    def _selector_match(labels: dict, selector: dict) -> bool:
        if not selector:
            return False
        for key, expected in selector.items():
            if labels.get(key) != expected:
                return False
        return True

    @staticmethod
    def _has_metrics_port(pod_spec: dict) -> bool:
        for container in pod_spec.get("containers") or []:
            for port in container.get("ports") or []:
                name = str(port.get("name") or "").strip().lower()
                if "metrics" in name:
                    return True
        return False

    def _resolve_owner(
        self,
        pod: dict,
        replicaset_cache: dict[tuple[str, str], dict],
        deployment_cache: dict[tuple[str, str], dict],
    ) -> _ResolvedOwner:
        metadata = pod.get("metadata") or {}
        namespace = str(metadata.get("namespace") or "")
        pod_name = str(metadata.get("name") or "")
        owner_refs = metadata.get("owner_references") or metadata.get("ownerReferences") or []

        if not owner_refs:
            return _ResolvedOwner(workload=pod_name, owner_resolution="fallback")

        owner = owner_refs[0]
        kind = str(owner.get("kind") or "")
        name = str(owner.get("name") or "")

        if kind == "Deployment" and name:
            return _ResolvedOwner(workload=name, owner_resolution="deployment")

        if kind != "ReplicaSet" or not name:
            return _ResolvedOwner(workload=name or pod_name, owner_resolution="fallback")

        rs_key = (namespace, name)
        replicaset = replicaset_cache.get(rs_key)
        if replicaset is None:
            try:
                replicaset = self.k8s.get_replicaset_raw(namespace=namespace, name=name)
            except Exception:
                return _ResolvedOwner(workload=name, owner_resolution="partial")
            replicaset_cache[rs_key] = replicaset

        rs_owner_refs = (
            replicaset.get("metadata", {}).get("owner_references")
            or replicaset.get("metadata", {}).get("ownerReferences")
            or []
        )
        for rs_owner in rs_owner_refs:
            if rs_owner.get("kind") != "Deployment":
                continue
            deployment_name = str(rs_owner.get("name") or "")
            if not deployment_name:
                continue

            dep_key = (namespace, deployment_name)
            if dep_key not in deployment_cache:
                try:
                    deployment_cache[dep_key] = self.k8s.get_deployment_raw(namespace, deployment_name)
                except Exception:
                    return _ResolvedOwner(workload=name, owner_resolution="partial")
            return _ResolvedOwner(workload=deployment_name, owner_resolution="deployment")

        return _ResolvedOwner(workload=name, owner_resolution="partial")

    def _collect_namespace_statuses(self, namespace: str) -> list[WorkloadStatusResponse]:
        pods = self.k8s.list_pods_raw(namespace=namespace)
        deployments = self.k8s.list_deployments_raw(namespace=namespace)
        metrics_by_pod = self.vllm.collect_namespace_metrics(namespace=namespace)
        now = int(time.time())

        replicaset_cache: dict[tuple[str, str], dict] = {}
        deployment_cache: dict[tuple[str, str], dict] = {
            (namespace, str(item.get("metadata", {}).get("name") or "")): item
            for item in deployments
            if item.get("metadata", {}).get("name")
        }

        deployment_candidates: dict[str, dict] = {}
        for deployment in deployments:
            metadata = deployment.get("metadata") or {}
            spec = deployment.get("spec") or {}
            template_spec = spec.get("template", {}).get("spec", {}) or {}
            if not self._has_metrics_port(template_spec):
                continue
            name = str(metadata.get("name") or "")
            if name:
                deployment_candidates[name] = deployment

        grouped_pods: dict[str, list[tuple[dict, _ResolvedOwner]]] = {
            workload: [] for workload in deployment_candidates
        }
        owner_resolution_by_workload: dict[str, str] = {}

        for pod in pods:
            spec = pod.get("spec") or {}
            if not self._has_metrics_port(spec):
                continue
            resolved = self._resolve_owner(pod, replicaset_cache, deployment_cache)
            grouped_pods.setdefault(resolved.workload, []).append((pod, resolved))
            owner_resolution_by_workload.setdefault(resolved.workload, resolved.owner_resolution)

        statuses: list[WorkloadStatusResponse] = []
        for workload_name in sorted(set(deployment_candidates) | set(grouped_pods)):
            deployment = deployment_candidates.get(workload_name)
            pod_entries = grouped_pods.get(workload_name, [])
            desired = self._deployment_desired_replicas(deployment) if deployment else len(pod_entries)
            replicas: list[WorkloadReplicaStatus] = []
            ready_count = 0
            metrics_available = 0
            latest_metric_ts = 0
            model_name: Optional[str] = None
            served_model_id: Optional[str] = None
            runtime_version: Optional[str] = None

            for pod, resolved in sorted(
                pod_entries,
                key=lambda item: str(item[0].get("metadata", {}).get("name") or ""),
            ):
                metadata = pod.get("metadata") or {}
                pod_name = str(metadata.get("name") or "")
                node_name = self._pod_node_name(pod)
                pod_ready = self._is_pod_ready(pod)
                phase = self._pod_phase(pod).lower()
                snapshot = metrics_by_pod.get(pod_name)
                latest_metric_ts = max(latest_metric_ts, snapshot.ts if snapshot else 0)

                if pod_ready:
                    ready_count += 1
                    replica_status = "ready" if snapshot and snapshot.has_any_metric() else "metrics_unavailable"
                else:
                    replica_status = "not_ready" if phase else "pending"

                replica = WorkloadReplicaStatus(
                    pod=pod_name,
                    node_name=node_name,
                    status=replica_status,
                    owner_resolution=resolved.owner_resolution,
                    pod_phase=self._pod_phase(pod) or None,
                    ready_condition=pod_ready,
                    metrics_observed_ts=snapshot.ts if snapshot else None,
                    metrics_freshness_seconds=(
                        round(max(0.0, time.time() - snapshot.ts), 3)
                        if snapshot and snapshot.ts > 0
                        else None
                    ),
                    generation_tokens_per_second=snapshot.generation_tokens_per_second if snapshot else None,
                    prompt_tokens_per_second=snapshot.prompt_tokens_per_second if snapshot else None,
                    waiting_requests=snapshot.waiting_requests if snapshot else None,
                    kv_cache_usage_percent=snapshot.kv_cache_usage_percent if snapshot else None,
                )
                if self._replica_has_metrics(replica):
                    metrics_available += 1

                if snapshot:
                    model_name = model_name or snapshot.model_name
                    served_model_id = served_model_id or snapshot.served_model_id
                    runtime_version = runtime_version or snapshot.runtime_version

                replicas.append(replica)

            metrics_unavailable = max(ready_count - metrics_available, 0)
            if ready_count == 0:
                workload_status = "not_ready"
            elif metrics_available == 0:
                workload_status = "metrics_unavailable"
            else:
                workload_status = "ready"

            image = None
            if deployment:
                containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers") or []
                if containers:
                    image = str(containers[0].get("image") or "")
            if not runtime_version and image and ":" in image:
                runtime_version = image.rsplit(":", 1)[-1]

            freshness_seconds = 0.0
            if latest_metric_ts > 0:
                freshness_seconds = max(0.0, time.time() - latest_metric_ts)

            statuses.append(
                WorkloadStatusResponse(
                    schema="pre6g.workload_status.v1",
                    ts=now,
                    freshness_seconds=round(freshness_seconds, 3),
                    query_window_seconds=self.query_window_seconds,
                    metrics_observed_ts=latest_metric_ts or None,
                    status=workload_status,
                    identity=WorkloadIdentity(
                        namespace=namespace,
                        workload=workload_name,
                        runtime="vllm",
                        model_name=model_name,
                        served_model_id=served_model_id,
                        runtime_image=image or None,
                        runtime_version=runtime_version,
                    ),
                    replica_summary=WorkloadReplicaSummary(
                        desired=desired,
                        ready=ready_count,
                        metrics_available=metrics_available,
                        metrics_unavailable=metrics_unavailable,
                    ),
                    replicas=replicas,
                    aggregate=WorkloadAggregateMetrics(
                        generation_tokens_per_second=self._sum(
                            replica.generation_tokens_per_second for replica in replicas
                        ),
                        prompt_tokens_per_second=self._sum(
                            replica.prompt_tokens_per_second for replica in replicas
                        ),
                        waiting_requests=self._sum(replica.waiting_requests for replica in replicas),
                        kv_cache_usage_percent_max=self._max(
                            replica.kv_cache_usage_percent for replica in replicas
                        ),
                    ),
                )
            )

        return statuses

    def get_workloads(self, namespace: str | None = None) -> WorkloadListResponse:
        target_namespace = (namespace or self.default_namespace).strip() or self.default_namespace
        cache_key = f"workloads::{target_namespace}"
        cached = self.cache.get(cache_key, ttl_seconds=2)
        if cached is not None:
            return cached

        statuses = self._collect_namespace_statuses(target_namespace)
        freshness_seconds = self._max(status.freshness_seconds for status in statuses) or 0.0
        items = [
            WorkloadListItem(
                namespace=status.identity.namespace,
                workload=status.identity.workload,
                runtime=status.identity.runtime,
                model_name=status.identity.model_name,
                runtime_image=status.identity.runtime_image,
                runtime_version=status.identity.runtime_version,
                nodes=sorted({replica.node_name for replica in status.replicas if replica.node_name}),
                status=status.status,
                desired_replicas=status.replica_summary.desired,
                ready_replicas=status.replica_summary.ready,
                generation_tokens_per_second=status.aggregate.generation_tokens_per_second,
                prompt_tokens_per_second=status.aggregate.prompt_tokens_per_second,
                waiting_requests=status.aggregate.waiting_requests,
                kv_cache_usage_percent_max=status.aggregate.kv_cache_usage_percent_max,
            )
            for status in statuses
        ]

        response = WorkloadListResponse(
            schema="pre6g.workload_list.v1",
            ts=int(time.time()),
            freshness_seconds=round(float(freshness_seconds), 3),
            query_window_seconds=self.query_window_seconds,
            count=len(items),
            workloads=items,
        )
        self.cache.set(cache_key, response)
        return response

    def get_workload_status(self, namespace: str, workload: str) -> WorkloadStatusResponse:
        cache_key = f"workloads::{namespace}::{workload}"
        cached = self.cache.get(cache_key, ttl_seconds=1)
        if cached is not None:
            return cached

        for status in self._collect_namespace_statuses(namespace):
            if status.identity.workload != workload:
                continue
            self.cache.set(cache_key, status)
            return status

        raise KeyError(f"unknown workload: {namespace}/{workload}")
