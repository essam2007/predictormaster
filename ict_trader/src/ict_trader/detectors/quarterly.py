"""Quarterly Theory AMD(X) phase refinement.

The default phase comes from the quarter index (Q1 accumulate, Q2 manipulate, Q3
distribute, Q4 continue). We refine it from observed behaviour: a quarter that sweeps a
prior extreme then reverses looks like manipulation; a strong one-directional expansion
looks like distribution.
"""

from __future__ import annotations

from ..clock import classify_amd
from ..domain.bars import Bar
from ..domain.enums import AMDPhase


def refine_amd(quarter_idx: int, quarter_bars: list[Bar]) -> AMDPhase:
    base = classify_amd(quarter_idx)
    closed = [b for b in quarter_bars if b.is_closed]
    if len(closed) < 3:
        return base

    rng = max(b.high for b in closed) - min(b.low for b in closed)
    if rng <= 0:
        return base
    net = closed[-1].close - closed[0].open
    directionality = abs(net) / rng

    # Strong one-way move => distribution regardless of base label.
    if directionality >= 0.6:
        return AMDPhase.DISTRIBUTION
    # Took out an early extreme then closed back inside => manipulation.
    first_third = closed[: max(1, len(closed) // 3)]
    swept_high = max(b.high for b in closed) > max(b.high for b in first_third)
    swept_low = min(b.low for b in closed) < min(b.low for b in first_third)
    if (swept_high or swept_low) and directionality < 0.3:
        return AMDPhase.MANIPULATION
    return base
