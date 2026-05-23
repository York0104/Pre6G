import json
from pathlib import Path
from typing import Any, Dict


class InventoryExtraAdapter:
    def __init__(self) -> None:
        base_dir = Path(__file__).resolve().parents[2]
        self.filepath = base_dir / "data" / "node_inventory_extra.json"

    def load_all(self) -> Dict[str, Any]:
        if not self.filepath.exists():
            return {}
        with open(self.filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_node_extra(self, node_name: str) -> Dict[str, Any]:
        return self.load_all().get(node_name, {})
