"""Walk-forward / expanding-window cross-validation.

Time-ordered splitting with mandatory burn-in. The trainer callable receives
*only* historical data; the validator hard-fails if a label outside the
training window leaks in.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np


@dataclass(frozen=True)
class Split:
    train_idx: np.ndarray
    test_idx: np.ndarray
    train_end: datetime
    test_end: datetime


def walk_forward_splits(
    timestamps: list[datetime],
    *,
    burn_in: timedelta,
    test_window: timedelta,
    step: timedelta | None = None,
    max_splits: int | None = None,
) -> Iterator[Split]:
    step = step or test_window
    ts = np.array(timestamps)
    if len(ts) == 0:
        return
    order = np.argsort(ts)
    ts = ts[order]
    start = ts[0]
    end = ts[-1]
    cur = start + burn_in
    yielded = 0
    while cur + test_window <= end:
        train_mask = ts <= cur
        test_mask = (ts > cur) & (ts <= cur + test_window)
        if test_mask.any():
            yield Split(
                train_idx=order[train_mask],
                test_idx=order[test_mask],
                train_end=cur,
                test_end=cur + test_window,
            )
            yielded += 1
            if max_splits is not None and yielded >= max_splits:
                return
        cur = cur + step


def evaluate_walk_forward(
    *,
    splits: Iterator[Split],
    train_fn: Callable[[np.ndarray], object],
    score_fn: Callable[[object, np.ndarray], dict[str, float]],
) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for s in splits:
        model = train_fn(s.train_idx)
        scores = score_fn(model, s.test_idx)
        scores["train_end"] = s.train_end.isoformat()
        scores["test_end"] = s.test_end.isoformat()
        out.append(scores)
    return out
