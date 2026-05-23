import time
from typing import Any, Optional


class SimpleTTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl_seconds: int) -> Optional[Any]:
        item = self._store.get(key)
        if item is None:
            return None

        ts, value = item
        if time.time() - ts > ttl_seconds:
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)