"""Shared detector helpers.

Detectors are *pure* functions of bar state — no I/O, no broker, no clock side effects —
so the backtester runs the identical code path as live. They operate on CLOSED bars only.
"""

from __future__ import annotations

from ..domain.bars import Bar


def swing_points(bars: list[Bar], strength: int = 2) -> tuple[list[int], list[int]]:
    """Return (swing_high_indices, swing_low_indices) using a fractal pivot of ``strength``.

    A swing high at i requires ``high[i]`` strictly greater than the ``strength`` highs on
    each side; symmetric for lows. The outermost ``strength`` bars can never be pivots.
    """
    highs: list[int] = []
    lows: list[int] = []
    n = len(bars)
    for i in range(strength, n - strength):
        window = bars[i - strength : i + strength + 1]
        hi = bars[i].high
        lo = bars[i].low
        if hi == max(b.high for b in window) and all(
            bars[i].high > bars[j].high for j in range(i - strength, i)
        ):
            highs.append(i)
        if lo == min(b.low for b in window) and all(
            bars[i].low < bars[j].low for j in range(i - strength, i)
        ):
            lows.append(i)
    return highs, lows


def dealing_range(bars: list[Bar], lookback: int = 40) -> tuple[float, float]:
    """The recent (low, high) used to split price into discount/premium halves."""
    window = bars[-lookback:] if lookback else bars
    if not window:
        return (0.0, 0.0)
    return (min(b.low for b in window), max(b.high for b in window))
