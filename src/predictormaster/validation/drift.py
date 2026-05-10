"""Drift detectors for streaming residual monitoring.

Implements:
  * Page-Hinkley: cumulative-deviation test for mean shifts
  * ADWIN: adaptive sliding window with sub-window comparison
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field


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

    Maintains a window of recent samples; whenever any split into a left and
    right sub-window shows mean separation beyond an epsilon-cut, the older
    half is dropped and `update` returns True.
    """

    delta: float = 0.002
    window: deque[float] = field(default_factory=deque)
    total: float = 0.0

    def _epsilon_cut(self, n0: int, n1: int) -> float:
        m = 1.0 / (1.0 / max(n0, 1) + 1.0 / max(n1, 1))
        var = self._variance()
        return math.sqrt(2.0 * m * var * math.log(2.0 / self.delta) / max(n0 + n1, 1)) + 2.0 / 3.0 * math.log(2.0 / self.delta) / m

    def _variance(self) -> float:
        if not self.window:
            return 1.0
        n = len(self.window)
        mean = self.total / n
        return sum((x - mean) ** 2 for x in self.window) / n

    def update(self, x: float) -> bool:
        self.window.append(x)
        self.total += x
        n = len(self.window)
        for split in range(1, n):
            n0 = split
            n1 = n - split
            left = list(self.window)[:n0]
            right = list(self.window)[n0:]
            mu0 = sum(left) / n0
            mu1 = sum(right) / n1
            if abs(mu0 - mu1) > self._epsilon_cut(n0, n1):
                # drop the older sub-window
                for _ in range(n0):
                    self.total -= self.window.popleft()
                return True
        return False
