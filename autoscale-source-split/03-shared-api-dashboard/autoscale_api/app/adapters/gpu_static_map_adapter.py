import json
from pathlib import Path
from typing import Dict, Optional


class GPUStaticMapAdapter:
    def __init__(self) -> None:
        base_dir = Path(__file__).resolve().parents[2]
        self.filepath = base_dir / "data" / "gpu_cuda_cores_map.json"

    def load_map(self) -> Dict[str, int]:
        if not self.filepath.exists():
            return {}
        with open(self.filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_cuda_cores(self, gpu_model: Optional[str]) -> Optional[int]:
        if not gpu_model:
            return None
        return self.load_map().get(gpu_model)
