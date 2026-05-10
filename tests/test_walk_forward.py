from __future__ import annotations

from datetime import datetime, timedelta, timezone

from predictormaster.validation.walk_forward import walk_forward_splits


def test_walk_forward_no_leakage():
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    timestamps = [base + timedelta(days=i) for i in range(120)]
    splits = list(
        walk_forward_splits(
            timestamps,
            burn_in=timedelta(days=30),
            test_window=timedelta(days=15),
            max_splits=5,
        )
    )
    assert splits, "expected at least one split"
    for s in splits:
        train_end = s.train_end
        for idx in s.train_idx:
            assert timestamps[idx] <= train_end
        for idx in s.test_idx:
            assert timestamps[idx] > train_end
            assert timestamps[idx] <= s.test_end
