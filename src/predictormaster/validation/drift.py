"""Drift detectors for streaming residual monitoring.

Implements:
  * Page-Hinkley: cumulative-deviation test for mean shifts
  * ADWIN: adaptive sliding window with exponential-histogram buckets,
    amortised O(log n) per update (Bifet & Gavaldà 2007)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ._adwin_buckets import BucketRows


@dataclass
class PageHinkley:
    delta: float = 0.005
    threshold: float = 50.0
    alpha: float = 0.9999
    mean: float = 0.0
    n: int = 0
    cum: float = 0.0
    minimum: float = 0.0

    def update(self, x: float) -> bool:
        self.n += 1
        self.mean = self.alpha * self.mean + (1 - self.alpha) * x
        self.cum += x - self.mean - self.delta
        self.minimum = min(self.minimum, self.cum)
        return (self.cum - self.minimum) > self.threshold


@dataclass
class ADWIN:
    """Concept-drift detector by Bifet & Gavaldà (2007).

    Maintains a sliding window represented as a row of exponential
    histograms. Every ``update`` checks each bucket-aligned cut for an
    epsilon-significant difference in means; on detection, the older
    sub-window is dropped and ``True`` is returned. Amortised cost is
    O(log n) per update.
    """

    delta: float = 0.002
    max_buckets_per_row: int = 5
    _rows: BucketRows = field(default_factory=BucketRows)

    @property
    def size(self) -> int:
        return self._rows.size

    @property
    def total(self) -> float:
        return self._rows.total

    def _epsilon_cut(self, n0: int, n1: int) -> float:
        m = 1.0 / (1.0 / max(n0, 1) + 1.0 / max(n1, 1))
        var = self._rows.variance() or 1.0
        denom = max(n0 + n1, 1)
        return math.sqrt(2.0 * m * var * math.log(2.0 / self.delta) / denom) + (
            2.0 / 3.0 * math.log(2.0 / self.delta) / m
        )

    def update(self, x: float) -> bool:
        if not self._rows.rows:
            self._rows.max_buckets_per_row = self.max_buckets_per_row
        self._rows.add(x)
        for n0, n1, mean0, mean1 in self._rows.cuts():
            if abs(mean0 - mean1) > self._epsilon_cut(n0, n1):
                self._rows.drop_left(n0)
                return True
        return False
