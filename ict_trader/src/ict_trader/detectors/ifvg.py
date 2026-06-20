"""Inverse Fair Value Gap + LTF entry trigger.

An FVG *inverts* only when a candle **body** (close) trades through it — a wick poke does
NOT qualify. A bearish FVG that price body-closes above flips to a bullish IFVG (support);
a bullish FVG body-closed below flips to a bearish IFVG (resistance). The LTF trigger is a
fresh same-direction FVG together with that inversion; the protective stop sits just
beyond the IFVG extreme.
"""

from __future__ import annotations

from ..domain.bars import Bar
from ..domain.enums import ComponentId, PDArrayKind, Side, Timeframe
from ..domain.pdarrays import FVG
from ..domain.signals import ComponentState
from .fvg import detect_fvgs


def find_inversions(bars: list[Bar], fvgs: list[FVG]) -> list[FVG]:
    """Return IFVGs produced by a body close through an opposing FVG."""
    inverted: list[FVG] = []
    for fvg in fvgs:
        for b in bars:
            if b.ts_open <= fvg.ts:
                continue
            # bearish FVG -> bullish IFVG when a body closes above its upper bound
            if fvg.side is Side.SHORT and b.close > fvg.upper:
                inverted.append(
                    FVG(side=Side.LONG, timeframe=fvg.timeframe, ts=b.ts_open,
                        lower=fvg.lower, upper=fvg.upper, kind=PDArrayKind.IFVG,
                        origin_ts=fvg.ts)
                )
                break
            # bullish FVG -> bearish IFVG when a body closes below its lower bound
            if fvg.side is Side.LONG and b.close < fvg.lower:
                inverted.append(
                    FVG(side=Side.SHORT, timeframe=fvg.timeframe, ts=b.ts_open,
                        lower=fvg.lower, upper=fvg.upper, kind=PDArrayKind.IFVG,
                        origin_ts=fvg.ts)
                )
                break
    return inverted


class LTFTriggerDetector:
    """LTF FVG + IFVG entry trigger. Emits entry + stop reference in the payload."""

    component = ComponentId.LTF_TRIGGER

    def __init__(self, *, tick_size: float = 0.25, min_ticks: float = 1.0,
                 stop_buffer_ticks: float = 2.0, recent: int = 30) -> None:
        self.tick_size = tick_size
        self.min_ticks = min_ticks
        self.stop_buffer_ticks = stop_buffer_ticks
        self.recent = recent

    def update(self, bars: list[Bar], timeframe: Timeframe, bias: Side) -> ComponentState:
        closed = [b for b in bars if b.is_closed]
        if len(closed) < 4 or bias is Side.NONE:
            return ComponentState(self.component, present=False, bias=bias)

        all_fvgs = detect_fvgs(closed, timeframe, tick_size=self.tick_size,
                               min_ticks=self.min_ticks)
        ifvgs = find_inversions(closed, all_fvgs)
        # IFVG must point the same way as our bias and be recent.
        recent_ts = closed[-self.recent].ts_open if len(closed) >= self.recent else closed[0].ts_open
        ifvg = next(
            (f for f in reversed(ifvgs) if f.side is bias and f.ts >= recent_ts),
            None,
        )
        if ifvg is None:
            return ComponentState(self.component, present=False, bias=bias,
                                  ts=closed[-1].ts_open)

        buf = self.stop_buffer_ticks * self.tick_size
        if bias is Side.LONG:
            entry = ifvg.mid
            stop = ifvg.lower - buf
        else:
            entry = ifvg.mid
            stop = ifvg.upper + buf
        return ComponentState(
            self.component, present=True, bias=bias, confidence=0.7,
            ts=closed[-1].ts_open,
            payload={"timeframe": timeframe.value, "entry": entry, "stop": stop,
                     "ifvg_lower": ifvg.lower, "ifvg_upper": ifvg.upper,
                     "origin_ts": ifvg.origin_ts.isoformat() if ifvg.origin_ts else None},
        )
