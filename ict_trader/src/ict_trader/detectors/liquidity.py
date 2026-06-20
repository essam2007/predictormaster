"""Liquidity pools and the external-range-liquidity (ERL) target.

Tracks the running day high/low (ERL), prior-day high/low, and equal-highs/lows pools. The
runner targets ERL: for a long, the opposing day high (buy-side liquidity above).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..domain.bars import Bar
from ..domain.enums import Side
from .base import swing_points


def equal_levels(
    bars: list[Bar], *, tick_size: float = 0.25, tol_ticks: float = 4.0, strength: int = 2
) -> tuple[list[float], list[float]]:
    """Cluster swing highs/lows that sit within ``tol_ticks`` into equal-highs/lows pools."""
    highs_idx, lows_idx = swing_points(bars, strength)
    tol = tick_size * tol_ticks
    eq_highs = _cluster([bars[i].high for i in highs_idx], tol)
    eq_lows = _cluster([bars[i].low for i in lows_idx], tol)
    return eq_highs, eq_lows


def _cluster(prices: list[float], tol: float) -> list[float]:
    pools: list[float] = []
    for p in sorted(prices):
        matched = [i for i in range(len(prices)) if abs(prices[i] - p) <= tol and prices[i] != p]
        if matched:
            pools.append(p)
    # de-duplicate clusters that are within tol of each other
    out: list[float] = []
    for p in sorted(set(pools)):
        if not out or abs(p - out[-1]) > tol:
            out.append(p)
    return out


@dataclass(slots=True)
class LiquidityState:
    """Per-day liquidity tracker. The engine feeds it ET-dated bars."""

    day_high: float | None = None
    day_low: float | None = None
    prior_day_high: float | None = None
    prior_day_low: float | None = None
    _current_date: date | None = field(default=None, repr=False)

    def update(self, bar: Bar, et_date: date) -> None:
        if self._current_date is None:
            self._current_date = et_date
        if et_date != self._current_date:
            self.prior_day_high = self.day_high
            self.prior_day_low = self.day_low
            self.day_high = bar.high
            self.day_low = bar.low
            self._current_date = et_date
            return
        self.day_high = bar.high if self.day_high is None else max(self.day_high, bar.high)
        self.day_low = bar.low if self.day_low is None else min(self.day_low, bar.low)

    def erl_target(self, side: Side) -> float | None:
        """The external liquidity the runner aims for."""
        return self.day_high if side is Side.LONG else self.day_low

    def daily_extreme_in(self, side: Side, latest_close: float, buffer: float = 0.0) -> bool:
        """Heuristic: is the directional draw already spent?

        For a long we are running toward the day high; if price is already at/above it the
        ERL is effectively taken and the high-probability run no longer exists.
        """
        if side is Side.LONG and self.day_high is not None:
            return latest_close >= self.day_high - buffer
        if side is Side.SHORT and self.day_low is not None:
            return latest_close <= self.day_low + buffer
        return False
