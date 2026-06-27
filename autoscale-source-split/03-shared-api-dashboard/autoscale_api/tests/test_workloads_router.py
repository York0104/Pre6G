import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import workloads as workloads_router
from app.schemas.workload import (
    WorkloadAggregateMetrics,
    WorkloadIdentity,
    WorkloadListItem,
    WorkloadListResponse,
    WorkloadReplicaStatus,
    WorkloadReplicaSummary,
    WorkloadStatusResponse,
)


class WorkloadsRouterTests(unittest.TestCase):
    def test_get_workloads_route_returns_service_payload(self) -> None:
        payload = WorkloadListResponse(
            schema="pre6g.workload_list.v1",
            ts=1710000001,
            freshness_seconds=0.4,
            query_window_seconds=10,
            count=1,
            workloads=[
                WorkloadListItem(
                    namespace="ai-serving",
                    workload="gemma4-e2b-vllm",
                runtime="vllm",
                model_name="gemma4-e2b-w4a16",
                runtime_image="vllm/vllm-openai:v0.23.0",
                runtime_version="v0.23.0",
                    nodes=["iccl-s3-251230"],
                    status="ready",
                    desired_replicas=1,
                    ready_replicas=1,
                    generation_tokens_per_second=92.4,
                    prompt_tokens_per_second=1042.8,
                    waiting_requests=2.0,
                    kv_cache_usage_percent_max=71.3,
                )
            ],
        )

        with patch.object(workloads_router.status_service, "get_workloads", return_value=payload):
            response = workloads_router.get_workloads(namespace="ai-serving")
        self.assertEqual(response.count, 1)
        self.assertEqual(response.workloads[0].workload, "gemma4-e2b-vllm")

    def test_get_workload_status_translates_missing_workload_to_404(self) -> None:
        with patch.object(
            workloads_router.status_service,
            "get_workload_status",
            side_effect=KeyError("unknown workload: ai-serving/missing"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                workloads_router.get_workload_status("ai-serving", "missing")

        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_workload_status_route_returns_service_payload(self) -> None:
        payload = WorkloadStatusResponse(
            schema="pre6g.workload_status.v1",
            ts=1710000001,
            freshness_seconds=0.2,
            query_window_seconds=10,
            status="ready",
            identity=WorkloadIdentity(
                namespace="ai-serving",
                workload="gemma4-e2b-vllm",
                runtime="vllm",
                model_name="gemma4-e2b-w4a16",
                served_model_id="gemma4-e2b-w4a16",
                runtime_image="vllm/vllm-openai:v0.23.0",
                runtime_version="v0.23.0",
            ),
            replica_summary=WorkloadReplicaSummary(
                desired=1,
                ready=1,
                metrics_available=1,
                metrics_unavailable=0,
            ),
            replicas=[
                WorkloadReplicaStatus(
                    pod="gemma4-e2b-vllm-abcde",
                    node_name="iccl-s3-251230",
                    status="ready",
                    owner_resolution="deployment",
                    pod_phase="Running",
                    ready_condition=True,
                    metrics_observed_ts=1710000001,
                    metrics_freshness_seconds=0.2,
                    generation_tokens_per_second=92.4,
                    prompt_tokens_per_second=1042.8,
                    waiting_requests=2.0,
                    kv_cache_usage_percent=71.3,
                )
            ],
            aggregate=WorkloadAggregateMetrics(
                generation_tokens_per_second=92.4,
                prompt_tokens_per_second=1042.8,
                waiting_requests=2.0,
                kv_cache_usage_percent_max=71.3,
            ),
        )

        with patch.object(workloads_router.status_service, "get_workload_status", return_value=payload):
            response = workloads_router.get_workload_status("ai-serving", "gemma4-e2b-vllm")
        self.assertEqual(response.status, "ready")
        self.assertEqual(response.identity.runtime_image, "vllm/vllm-openai:v0.23.0")
        self.assertEqual(response.identity.runtime_version, "v0.23.0")


if __name__ == "__main__":
    unittest.main()
