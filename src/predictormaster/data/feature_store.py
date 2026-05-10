"""Point-in-time feature store with leakage guard.

The store is split into:

* offline tier: append-only Parquet partitions, queried by feature name +
  asof-timestamp. Reads return only rows whose `valid_from <= asof` AND
  (`valid_to IS NULL` OR `valid_to > asof`), giving correct point-in-time joins.
* online tier: a small key/value face for sub-millisecond reads at inference
  time, populated by the same writer that updates the offline tier.

This module ships an in-memory implementation suitable for tests and a
Redis/Parquet pair behind the same interface for production. Adapters live in
`predictormaster.data.ingestion`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FeatureKey:
    feature: str
    entity_id: str


@dataclass(frozen=True)
class FeatureRow:
    key: FeatureKey
    value: Any
    valid_from: datetime
    valid_to: datetime | None = None
    source_version: str = "0"


class FeatureStore(ABC):
    @abstractmethod
    def write(self, rows: list[FeatureRow]) -> None: ...

    @abstractmethod
    def asof(
        self,
        feature: str,
        entity_ids: list[str],
        asof: datetime,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def online_get(self, feature: str, entity_id: str) -> Any | None: ...


@dataclass
class InMemoryFeatureStore(FeatureStore):
    """Reference implementation. Correct PIT semantics, useful in tests."""

    _rows: dict[FeatureKey, list[FeatureRow]] = field(default_factory=lambda: defaultdict(list))
    _online: dict[FeatureKey, Any] = field(default_factory=dict)

    def write(self, rows: list[FeatureRow]) -> None:
        for r in rows:
            bucket = self._rows[r.key]
            bucket.append(r)
            bucket.sort(key=lambda x: x.valid_from)
            cur = self._online.get(r.key)
            if cur is None or self._latest_for(r.key).valid_from <= r.valid_from:
                self._online[r.key] = r.value

    def _latest_for(self, key: FeatureKey) -> FeatureRow:
        return self._rows[key][-1]

    def asof(self, feature: str, entity_ids: list[str], asof: datetime) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for eid in entity_ids:
            bucket = self._rows.get(FeatureKey(feature, eid), [])
            chosen: FeatureRow | None = None
            for r in bucket:
                if r.valid_from <= asof and (r.valid_to is None or r.valid_to > asof):
                    chosen = r
                else:
                    if r.valid_from > asof:
                        break
            out[eid] = chosen.value if chosen is not None else None
        return out

    def online_get(self, feature: str, entity_id: str) -> Any | None:
        return self._online.get(FeatureKey(feature, entity_id))


class LeakageError(RuntimeError):
    pass


def assert_no_leakage(
    *,
    feature_timestamps: list[datetime],
    label_timestamp: datetime,
) -> None:
    """Block any training row whose features post-date the label.

    Called at the boundary between feature assembly and trainer input. Failing
    fast here prevents the most common bug class in sports modelling.
    """
    bad = [t for t in feature_timestamps if t > label_timestamp]
    if bad:
        raise LeakageError(
            f"{len(bad)} feature timestamps post-date label at {label_timestamp.isoformat()}"
        )
