"""Aggregate 1-minute bars into higher timeframes on a fixed wall-clock grid.

Bars are aligned to minute-of-day boundaries (e.g. 5m -> :00/:05/...; 1h -> :00) so ES and
NQ share identical ``ts_open`` and can be paired into co-bars. A higher-timeframe bar is
emitted *closed* only when a 1-minute bar from the next period arrives, so detectors never
see a provisional aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..domain.bars import Bar
from ..domain.enums import Symbol, Timeframe


def period_start(ts: datetime, tf: Timeframe) -> datetime:
    """Floor ``ts`` to the start of its ``tf`` period (using ET wall clock minutes)."""
    minute_of_day = ts.hour * 60 + ts.minute
    floored = (minute_of_day // tf.minutes) * tf.minutes
    return ts.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)


@dataclass
class _Building:
    ts_open: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def merge(self, bar: Bar) -> None:
        self.high = max(self.high, bar.high)
        self.low = min(self.low, bar.low)
        self.close = bar.close
        self.volume += bar.volume


class TimeframeAggregator:
    """Aggregates 1-minute bars of one symbol into one target timeframe."""

    def __init__(self, symbol: Symbol, timeframe: Timeframe) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self._cur: _Building | None = None

    def add(self, m1: Bar) -> Bar | None:
        """Feed a closed 1-minute bar; return a newly *closed* aggregate bar if one rolled."""
        if m1.timeframe is not Timeframe.M1:
            raise ValueError("TimeframeAggregator consumes 1-minute bars")
        start = period_start(m1.ts_open, self.timeframe)
        emitted: Bar | None = None
        if self._cur is None:
            self._cur = _Building(start, m1.open, m1.high, m1.low, m1.close, m1.volume)
        elif start > self._cur.ts_open:
            emitted = self._flush()
            self._cur = _Building(start, m1.open, m1.high, m1.low, m1.close, m1.volume)
        else:
            self._cur.merge(m1)
        return emitted

    def _flush(self) -> Bar:
        b = self._cur
        assert b is not None
        return Bar(self.symbol, self.timeframe, b.ts_open, b.open, b.high, b.low,
                   b.close, b.volume, is_closed=True)

    def provisional(self) -> Bar | None:
        """The current still-building (un-closed) aggregate, for the live monitor only."""
        if self._cur is None:
            return None
        b = self._cur
        return Bar(self.symbol, self.timeframe, b.ts_open, b.open, b.high, b.low,
                   b.close, b.volume, is_closed=False)


class MultiTimeframeBuilder:
    """Maintains aggregators for all timeframes for one symbol."""

    TIMEFRAMES = (Timeframe.M3, Timeframe.M5, Timeframe.M15, Timeframe.H1)

    def __init__(self, symbol: Symbol) -> None:
        self.symbol = symbol
        self._aggs = {tf: TimeframeAggregator(symbol, tf) for tf in self.TIMEFRAMES}

    def add(self, m1: Bar) -> dict[Timeframe, Bar]:
        """Return the map of timeframes that produced a newly-closed bar from this m1."""
        out: dict[Timeframe, Bar] = {Timeframe.M1: m1}
        for tf, agg in self._aggs.items():
            closed = agg.add(m1)
            if closed is not None:
                out[tf] = closed
        return out
