"""Thread-safe tag value store, quality handling and gateway status."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

QUALITY_GOOD = "Good"
QUALITY_BAD = "Bad"
QUALITY_UNCERTAIN = "Uncertain"


@dataclass
class TagValue:
    name: str
    value: Any = None
    quality: str = QUALITY_UNCERTAIN
    timestamp: float = field(default_factory=time.time)
    error: str = ""


class TagStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, TagValue] = {}

    def update(self, name: str, value: Any, quality: str = QUALITY_GOOD, error: str = "") -> None:
        with self._lock:
            self._values[name] = TagValue(name, value, quality, time.time(), error)

    def set_quality(self, name: str, quality: str, error: str = "") -> None:
        with self._lock:
            value = self._values.get(name)
            if value is None:
                value = TagValue(name, None, quality, time.time(), error)
            else:
                value.quality = quality
                value.error = error
            self._values[name] = value

    def get(self, name: str) -> TagValue | None:
        with self._lock:
            v = self._values.get(name)
            return TagValue(**v.__dict__) if v else None

    def snapshot(self) -> dict[str, TagValue]:
        with self._lock:
            return {k: TagValue(**v.__dict__) for k, v in self._values.items()}

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def remove(self, name: str) -> None:
        with self._lock:
            self._values.pop(name, None)

    def names(self) -> list[str]:
        with self._lock:
            return list(self._values.keys())


@dataclass
class GatewayStatus:
    running: bool = False
    plc_connected: bool = False
    plc_message: str = ""
    polls_total: int = 0
    polls_error: int = 0
    reads_last: int = 0
    last_poll_ms: float = 0.0
    last_poll_time: float = 0.0
    db_connected: bool = False
    db_message: str = ""
    db_rows_written: int = 0
    db_queue_size: int = 0
    gateway_uptime: float = 0.0


class StatusStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = GatewayStatus()

    def set(self, **kwargs: Any) -> None:
        with self._lock:
            status = self._status
            for k, v in kwargs.items():
                if hasattr(status, k):
                    setattr(status, k, v)

    def update(self, delta: dict[str, Any]) -> None:
        self.set(**delta)

    def get(self) -> GatewayStatus:
        with self._lock:
            status = self._status
            return GatewayStatus(**status.__dict__)