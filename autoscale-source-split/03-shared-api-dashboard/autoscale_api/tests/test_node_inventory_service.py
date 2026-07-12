from app.services.node_inventory_service import NodeInventoryService


def _raw_gpu_node(node_name="icclz1", labels=None):
    return {
        "metadata": {
            "name": node_name,
            "labels": labels
            or {
                "feature.node.kubernetes.io/pci-10de.present": "true",
            },
        },
        "status": {
            "addresses": [{"type": "InternalIP", "address": "100.105.48.97"}],
            "node_info": {
                "os_image": "Ubuntu 22.04.5 LTS",
                "kernel_version": "6.8.0-124-generic",
                "container_runtime_version": "containerd://2.2.3-k3s1",
            },
            "capacity": {"cpu": "8", "memory": "6582084Ki", "nvidia.com/gpu.shared": "4"},
        },
    }


def test_icclz1_uses_static_gpu_inventory_when_discovery_is_incomplete(monkeypatch):
    service = NodeInventoryService()
    monkeypatch.setattr(service, "_infer_gpu_models_from_aggregator", lambda _node: [])

    node = service.build_node_inventory(_raw_gpu_node())

    assert node.gpu.models == ["NVIDIA GeForce GTX 1080 Ti"]
    assert node.gpu.memory == "11264 MiB"
    assert node.gpu.compute_capability == "6.1"
    assert node.gpu.cuda_cores == 3584


def test_discovered_gpu_product_takes_precedence_over_static_inventory(monkeypatch):
    service = NodeInventoryService()
    labels = {
        "feature.node.kubernetes.io/pci-10de.present": "true",
        "nvidia.com/gpu.product": "Discovered GPU",
        "nvidia.com/gpu.memory": "24564",
        "nvidia.com/gpu.compute.major": "8",
        "nvidia.com/gpu.compute.minor": "9",
    }

    node = service.build_node_inventory(_raw_gpu_node(labels=labels))

    assert node.gpu.models == ["Discovered GPU"]
    assert node.gpu.memory == "24564 MiB"
    assert node.gpu.compute_capability == "8.9"


def test_unknown_gpu_node_keeps_generic_fallback(monkeypatch):
    service = NodeInventoryService()
    monkeypatch.setattr(service, "_infer_gpu_models_from_aggregator", lambda _node: [])

    node = service.build_node_inventory(_raw_gpu_node(node_name="unknown-gpu"))

    assert node.gpu.models == ["NVIDIA GPU"]
