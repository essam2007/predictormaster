"""PD-array (Premium/Discount array) value objects: FVG, Inverse-FVG, etc.

A *fair value gap* is a 3-candle imbalance. A *bullish* FVG is the gap between candle-1's
high and candle-3's low (price delivered up so fast it left an unfilled void below); a
*bearish* FVG is the gap between candle-1's low and candle-3's high.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .enums import PDArrayKind, Side, Timeframe


@dataclass(slots=True)
class FVG:
    """A fair value gap. ``lower``/``upper`` are the gap bounds (lower < upper)."""

    side: Side  # LONG = bullish FVG (support), SHORT = bearish FVG (resistance)
    timeframe: Timeframe
    ts: datetime  # open time of the third candle that completed the gap
    lower: float
    upper: float
    kind: PDArrayKind = PDArrayKind.FVG
    filled: bool = False
    # For an inverse FVG, the FVG it originated from before polarity flip.
    origin_ts: datetime | None = None

    @property
    def mid(self) -> float:
        """Consequent encroachment — the 50% level."""
        return (self.lower + self.upper) / 2.0

    @property
    def size(self) -> float:
        return self.upper - self.lower

    def contains(self, price: float) -> bool:
        return self.lower <= price <= self.upper

    def is_discount(self, range_low: float, range_high: float) -> bool:
        """True if the gap mid sits in the lower (discount) half of a dealing range."""
        if range_high <= range_low:
            return False
        return self.mid <= (range_low + range_high) / 2.0

    def is_premium(self, range_low: float, range_high: float) -> bool:
        if range_high <= range_low:
            return False
        return self.mid >= (range_low + range_high) / 2.0


@dataclass(slots=True)
class LiquidityLevel:
    """A pool of resting liquidity (session/PD highs-lows, equal highs/lows)."""

    price: float
    kind: str
    ts: datetime
    swept: bool = False


@dataclass(slots=True)
class PDArrayRegistry:
    """Active PD-arrays per timeframe, used by the LRLR path scan."""

    fvgs: list[FVG] = field(default_factory=list)

    def add(self, fvg: FVG) -> None:
        self.fvgs.append(fvg)

    def opposing(self, side: Side) -> list[FVG]:
        """Unfilled arrays that would oppose a move in ``side`` direction.

        A long run upward is opposed by bearish (resistance) FVGs above; a short run down
        is opposed by bullish (support) FVGs below.
        """
        opp = side.opposite
        return [f for f in self.fvgs if f.side is opp and not f.filled]
