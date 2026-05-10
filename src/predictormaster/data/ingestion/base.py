"""Adapter base class with deterministic idempotency keys and SLA metadata."""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class SLA:
    name: str
    refresh: timedelta
    latency_budget: timedelta
    severity: str = "critical"


@dataclass(frozen=True)
class Envelope:
    source: str
    fetched_utc: datetime
    payload: dict[str, Any]

    def idempotency_key(self) -> str:
        body = json.dumps(self.payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(self.source.encode() + b"|" + body).hexdigest()


class Source(ABC):
    sla: SLA

    @abstractmethod
    def fetch(self, *, asof: datetime | None = None) -> list[Envelope]: ...

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
