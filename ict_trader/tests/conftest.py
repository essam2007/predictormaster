"""Shared test helpers for building synthetic candles."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ict_trader.domain.bars import Bar
from ict_trader.domain.enums import Symbol, Timeframe

ET = ZoneInfo("America/New_York")


def mk_bar(
    i: int,
    o: float,
    h: float,
    low: float,
    c: float,
    *,
    symbol: Symbol = Symbol.NQ,
    timeframe: Timeframe = Timeframe.M5,
    start: datetime | None = None,
    is_closed: bool = True,
) -> Bar:
    """Build a bar at index ``i`` minutes (scaled by timeframe) from ``start``."""
    base = start or datetime(2024, 5, 15, 9, 0, tzinfo=ET)
    ts = base + timedelta(minutes=i * timeframe.minutes)
    return Bar(symbol=symbol, timeframe=timeframe, ts_open=ts, open=o, high=h,
               low=low, close=c, is_closed=is_closed)


def series_from(rows: list[tuple[float, float, float, float]], **kw) -> list[Bar]:
    """Build a list of bars from (open, high, low, close) tuples."""
    return [mk_bar(i, *row, **kw) for i, row in enumerate(rows)]
