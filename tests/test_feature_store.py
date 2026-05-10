from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from predictormaster.data.feature_store import (
    FeatureKey,
    FeatureRow,
    InMemoryFeatureStore,
    LeakageError,
    assert_no_leakage,
)


def test_pit_returns_value_valid_at_asof():
    store = InMemoryFeatureStore()
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    store.write([
        FeatureRow(key=FeatureKey("form", "p1"), value=0.5, valid_from=t0),
        FeatureRow(key=FeatureKey("form", "p1"), value=0.7, valid_from=t0 + timedelta(days=2)),
    ])
    out = store.asof("form", ["p1"], t0 + timedelta(days=1))
    assert out["p1"] == 0.5
    out2 = store.asof("form", ["p1"], t0 + timedelta(days=3))
    assert out2["p1"] == 0.7


def test_unknown_entity_returns_none():
    store = InMemoryFeatureStore()
    out = store.asof("form", ["nope"], datetime.now(timezone.utc))
    assert out["nope"] is None


def test_leakage_guard_raises():
    label_t = datetime(2025, 1, 5, tzinfo=timezone.utc)
    feature_ts = [
        datetime(2025, 1, 4, tzinfo=timezone.utc),
        datetime(2025, 1, 6, tzinfo=timezone.utc),
    ]
    with pytest.raises(LeakageError):
        assert_no_leakage(feature_timestamps=feature_ts, label_timestamp=label_t)
