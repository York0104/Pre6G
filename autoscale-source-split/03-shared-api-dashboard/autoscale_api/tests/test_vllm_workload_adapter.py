import unittest

from app.adapters.vllm_workload_adapter import VllmWorkloadAdapter


class FakeVllmWorkloadAdapter(VllmWorkloadAdapter):
    def __init__(self, responses: dict[tuple[str, str], list[dict]]) -> None:
        super().__init__(vm_url="http://example.invalid", query_window_seconds=10)
        self.responses = responses

    def _query_metric_vector(self, metric_candidates, namespace: str, mode: str):
        for metric_name in metric_candidates:
            key = (metric_name, mode)
            if key in self.responses:
                return metric_name, self.responses[key]
        return None, []


class VllmWorkloadAdapterTests(unittest.TestCase):
    def test_collect_namespace_metrics_merges_multiple_semantics(self) -> None:
        adapter = FakeVllmWorkloadAdapter(
            responses={
                ("vllm:generation_tokens_total", "rate"): [
                    {
                        "metric": {
                            "kubernetes_namespace": "ai-serving",
                            "kubernetes_pod": "gemma-pod-1",
                            "kubernetes_node": "iccl-s3-251230",
                            "model_name": "gemma4-e2b-w4a16",
                        },
                        "value": [1710000001, "91.25"],
                    }
                ],
                ("vllm:prompt_tokens_total", "rate"): [
                    {
                        "metric": {
                            "kubernetes_namespace": "ai-serving",
                            "kubernetes_pod": "gemma-pod-1",
                            "kubernetes_node": "iccl-s3-251230",
                        },
                        "value": [1710000001, "1042.8"],
                    }
                ],
                ("vllm:num_requests_waiting", "gauge"): [
                    {
                        "metric": {
                            "kubernetes_namespace": "ai-serving",
                            "kubernetes_pod": "gemma-pod-1",
                            "kubernetes_node": "iccl-s3-251230",
                        },
                        "value": [1710000001, "2"],
                    }
                ],
                ("vllm:gpu_cache_usage_perc", "gauge"): [
                    {
                        "metric": {
                            "kubernetes_namespace": "ai-serving",
                            "kubernetes_pod": "gemma-pod-1",
                            "kubernetes_node": "iccl-s3-251230",
                        },
                        "value": [1710000001, "0.713"],
                    }
                ],
                ("vllm:info", "gauge"): [
                    {
                        "metric": {
                            "kubernetes_namespace": "ai-serving",
                            "kubernetes_pod": "gemma-pod-1",
                            "version": "v0.23.0",
                            "served_model_id": "gemma4-e2b-w4a16",
                        },
                        "value": [1710000001, "1"],
                    }
                ],
            }
        )

        snapshots = adapter.collect_namespace_metrics("ai-serving")
        snapshot = snapshots["gemma-pod-1"]

        self.assertEqual(snapshot.model_name, "gemma4-e2b-w4a16")
        self.assertEqual(snapshot.runtime_version, "v0.23.0")
        self.assertEqual(snapshot.served_model_id, "gemma4-e2b-w4a16")
        self.assertAlmostEqual(snapshot.generation_tokens_per_second or 0.0, 91.25)
        self.assertAlmostEqual(snapshot.prompt_tokens_per_second or 0.0, 1042.8)
        self.assertAlmostEqual(snapshot.waiting_requests or 0.0, 2.0)
        self.assertAlmostEqual(snapshot.kv_cache_usage_percent or 0.0, 71.3)
        self.assertTrue(snapshot.has_any_metric())


if __name__ == "__main__":
    unittest.main()
