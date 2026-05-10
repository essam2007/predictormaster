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

import bisect
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
    _starts: dict[FeatureKey, list[datetime]] = field(default_factory=lambda: defaultdict(list))
    _online: dict[FeatureKey, Any] = field(default_factory=dict)

    def write(self, rows: list[FeatureRow]) -> None:
        for r in rows:
            bucket = self._rows[r.key]
            starts = self._starts[r.key]
            # Keep both lists sorted on valid_from in O(log n).
            i = bisect.bisect_right(starts, r.valid_from)
            bucket.insert(i, r)
            starts.insert(i, r.valid_from)
            cur = self._online.get(r.key)
            if cur is None or bucket[-1].valid_from <= r.valid_from:
                self._online[r.key] = r.value

    def asof(self, feature: str, entity_ids: list[str], asof: datetime) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for eid in entity_ids:
            key = FeatureKey(feature, eid)
            bucket = self._rows.get(key)
            if not bucket:
                out[eid] = None
                continue
            starts = self._starts[key]
            # Largest index with valid_from <= asof.
            idx = bisect.bisect_right(starts, asof) - 1
            chosen: Any | None = None
            while idx >= 0:
                r = bucket[idx]
                if r.valid_to is None or r.valid_to > asof:
                    chosen = r.value
                    break
                idx -= 1
            out[eid] = chosen
        return out

    def online_get(self, feature: str, entity_id: str) -> Any | None:
        return self._online.get(FeatureKey(feature, entity_id))


class LeakageError(RuntimeError):
    pass


def assert_no_leakage(
    *,
    feature_timestamps: list[datetime],
    label_timestamp: datetime,
    valid_to_timestamps: list[datetime | None] | None = None,
) -> None:
    """Block any training row whose features post-date the label, and
    optionally any row whose feature has already expired by label time.

    Called at the boundary between feature assembly and trainer input.
    Failing fast here prevents the most common bug class in sports
    modelling.
    """
    bad_future = [t for t in feature_timestamps if t > label_timestamp]
    if bad_future:
        raise LeakageError(
            f"{len(bad_future)} feature timestamps post-date label at {label_timestamp.isoformat()}"
        )
    if valid_to_timestamps is not None:
        if len(valid_to_timestamps) != len(feature_timestamps):
            raise ValueError("valid_to_timestamps length must match feature_timestamps")
        bad_expired = [
            (i, vt)
            for i, vt in enumerate(valid_to_timestamps)
            if vt is not None and vt <= label_timestamp
        ]
        if bad_expired:
            raise LeakageError(
                f"{len(bad_expired)} features expired before label at {label_timestamp.isoformat()}"
            )
