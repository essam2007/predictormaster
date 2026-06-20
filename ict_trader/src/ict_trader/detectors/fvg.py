"""Fair Value Gap detection (HTF bias component).

A bullish FVG (support) exists at candle ``i`` when ``low[i] > high[i-2]`` — price
delivered up so fast it left an unfilled void. A bearish FVG (resistance) exists when
``high[i] < low[i-2]``.
"""

from __future__ import annotations

from ..domain.bars import Bar
from ..domain.enums import ComponentId, Side, Timeframe
from ..domain.pdarrays import FVG
from ..domain.signals import ComponentState
from .base import dealing_range


def detect_fvgs(
    bars: list[Bar],
    timeframe: Timeframe,
    *,
    tick_size: float = 0.25,
    min_ticks: float = 1.0,
) -> list[FVG]:
    """Scan closed bars and return every FVG (unfilled status resolved separately)."""
    out: list[FVG] = []
    min_size = tick_size * min_ticks
    for i in range(2, len(bars)):
        c1, _c2, c3 = bars[i - 2], bars[i - 1], bars[i]
        # bullish: gap between c1.high and c3.low
        if c3.low > c1.high and (c3.low - c1.high) >= min_size:
            out.append(
                FVG(side=Side.LONG, timeframe=timeframe, ts=c3.ts_open,
                    lower=c1.high, upper=c3.low)
            )
        # bearish: gap between c3.high and c1.low
        elif c3.high < c1.low and (c1.low - c3.high) >= min_size:
            out.append(
                FVG(side=Side.SHORT, timeframe=timeframe, ts=c3.ts_open,
                    lower=c3.high, upper=c1.low)
            )
    return out


def resolve_fills(fvgs: list[FVG], bars_after: list[Bar]) -> None:
    """Mark FVGs *mitigated* in place — i.e. fully traded through.

    Per the research's S/R-vs-mitigated distinction, an FVG that price merely reacts at
    (its edge or 50% consequent encroachment) still holds; only a body close beyond the
    far boundary invalidates it. A bullish FVG is therefore mitigated when a later bar
    *closes* below its lower bound; a bearish FVG when a bar closes above its upper bound.
    """
    for fvg in fvgs:
        if fvg.filled:
            continue
        for b in bars_after:
            if b.ts_open <= fvg.ts:
                continue
            if fvg.side is Side.LONG and b.close < fvg.lower:
                fvg.filled = True
                break
            if fvg.side is Side.SHORT and b.close > fvg.upper:
                fvg.filled = True
                break


class FVGDetector:
    """HTF bias component.

    Returns ``present`` when there is an unfilled FVG in the candidate bias direction that
    sits in the correct half of the dealing range (discount for longs, premium for shorts)
    and into which price is currently delivering.
    """

    component = ComponentId.FVG

    def __init__(self, *, tick_size: float = 0.25, min_ticks: float = 1.0,
                 lookback: int = 40) -> None:
        self.tick_size = tick_size
        self.min_ticks = min_ticks
        self.lookback = lookback

    def update(self, bars: list[Bar], timeframe: Timeframe, bias: Side) -> ComponentState:
        closed = [b for b in bars if b.is_closed]
        if len(closed) < 3 or bias is Side.NONE:
            return ComponentState(self.component, present=False, bias=bias)

        fvgs = detect_fvgs(closed, timeframe, tick_size=self.tick_size,
                           min_ticks=self.min_ticks)
        resolve_fills(fvgs, closed)
        rng_low, rng_high = dealing_range(closed, self.lookback)
        price = closed[-1].close

        last = closed[-1]
        candidates = [f for f in fvgs if f.side is bias and not f.filled]
        chosen: FVG | None = None
        for f in reversed(candidates):
            in_zone = (
                f.is_discount(rng_low, rng_high) if bias is Side.LONG
                else f.is_premium(rng_low, rng_high)
            )
            # "delivering into it": the latest bar has tagged the gap from the correct
            # side (low into a discount FVG for longs / high into a premium FVG for
            # shorts) without invalidating it.
            if bias is Side.LONG:
                delivering = last.low <= f.upper
            else:
                delivering = last.high >= f.lower
            if in_zone and delivering:
                chosen = f
                break

        if chosen is None:
            return ComponentState(self.component, present=False, bias=bias,
                                  ts=closed[-1].ts_open)
        # confidence rises the closer price is to consequent encroachment (the mid).
        dist = abs(price - chosen.mid)
        conf = max(0.4, 1.0 - dist / max(chosen.size, self.tick_size))
        return ComponentState(
            self.component, present=True, bias=bias, confidence=round(conf, 3),
            ts=closed[-1].ts_open,
            payload={"timeframe": timeframe.value, "lower": chosen.lower,
                     "upper": chosen.upper, "mid": chosen.mid},
        )
