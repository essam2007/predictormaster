"""Thread-safe in-memory snapshot store backing the /live endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from .fusion import LiveSentiment


@dataclass
class SnapshotStore:
    _items: dict[str, LiveSentiment] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    def put(self, s: LiveSentiment) -> None:
        with self._lock:
            self._items[s.game_id] = s

    def get(self, game_id: str) -> LiveSentiment | None:
        with self._lock:
            return self._items.get(game_id)

    def list(self) -> list[LiveSentiment]:
        with self._lock:
            return list(self._items.values())

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_STORE = SnapshotStore()


def store() -> SnapshotStore:
    return _STORE
