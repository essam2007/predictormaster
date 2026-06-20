"""Market structure: swing tracking, displacement, and BOS/MSS.

This is the ONLY source that authorizes a breakeven/trail move in the position manager —
which is how we avoid the documented "breakeven on the first pullback" leak.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.bars import Bar
from ..domain.enums import Side
from .base import swing_points


@dataclass(slots=True)
class StructureView:
    last_swing_high: float | None
    last_swing_low: float | None
    bos: bool  # break of structure in favor
    displacement: bool  # large-body expansion leg in favor
    trail_to: float | None  # the protective level to trail behind


def _avg_body(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    return sum(b.body for b in bars) / len(bars)


def analyze(bars: list[Bar], side: Side, *, strength: int = 2,
            displacement_mult: float = 1.8) -> StructureView:
    """Compute the structure view for a position in ``side`` direction."""
    closed = [b for b in bars if b.is_closed]
    highs_idx, lows_idx = swing_points(closed, strength)
    last_high = closed[highs_idx[-1]].high if highs_idx else None
    last_low = closed[lows_idx[-1]].low if lows_idx else None

    bos = False
    trail_to: float | None = None
    if side is Side.LONG:
        # BOS = close above the most recent swing high; trail behind the most recent
        # higher-low (the last swing low).
        if last_high is not None and closed[-1].close > last_high:
            bos = True
        trail_to = last_low
    elif side is Side.SHORT:
        if last_low is not None and closed[-1].close < last_low:
            bos = True
        trail_to = last_high

    avg = _avg_body(closed[-20:])
    last = closed[-1]
    displaced = last.body >= displacement_mult * avg and (
        (side is Side.LONG and last.is_bullish) or (side is Side.SHORT and last.is_bearish)
    )
    return StructureView(last_high, last_low, bos, displaced, trail_to)
