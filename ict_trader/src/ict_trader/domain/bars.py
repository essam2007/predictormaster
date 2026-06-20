"""Bar / candle value objects and a lightweight rolling series.

Bars are immutable. The detectors operate only on *closed* bars; intrabar values are
carried as ``is_closed=False`` and treated as provisional everywhere.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime

from .enums import Symbol, Timeframe


@dataclass(frozen=True, slots=True)
class Bar:
    """A single OHLC bar.

    ``ts_open`` is the timezone-aware open time. All bars in the system are aligned to a
    fixed grid (see :mod:`ict_trader.clock`) so that ES and NQ bars share timestamps.
    """

    symbol: Symbol
    timeframe: Timeframe
    ts_open: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    is_closed: bool = True

    def __post_init__(self) -> None:
        if self.ts_open.tzinfo is None:
            raise ValueError("Bar.ts_open must be timezone-aware")
        if self.high < self.low:
            raise ValueError(f"Bar high {self.high} < low {self.low}")

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_doji(self) -> bool:
        # Body smaller than 10% of range is treated as flat (no directional close).
        return self.range <= 0 or self.body <= 0.1 * self.range


@dataclass(frozen=True, slots=True)
class CoBar:
    """A time-aligned pair of ES and NQ bars used for cross-instrument analysis.

    ``degraded`` is set when one feed's bar is missing/late: SMT and PSP refuse to fire on
    degraded co-bars so we never fabricate a divergence on unsynced data.
    """

    ts_open: datetime
    timeframe: Timeframe
    es: Bar | None
    nq: Bar | None

    @property
    def degraded(self) -> bool:
        return self.es is None or self.nq is None


class Series:
    """A bounded rolling window of bars for one (symbol, timeframe)."""

    def __init__(self, symbol: Symbol, timeframe: Timeframe, maxlen: int = 5000) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self._bars: deque[Bar] = deque(maxlen=maxlen)

    def append(self, bar: Bar) -> None:
        if bar.symbol is not self.symbol or bar.timeframe is not self.timeframe:
            raise ValueError("bar does not match this series")
        # Replace a trailing provisional bar at the same timestamp (live intrabar update).
        if self._bars and self._bars[-1].ts_open == bar.ts_open:
            self._bars[-1] = bar
        else:
            self._bars.append(bar)

    def extend(self, bars: Iterable[Bar]) -> None:
        for b in bars:
            self.append(b)

    @property
    def closed(self) -> list[Bar]:
        return [b for b in self._bars if b.is_closed]

    def __len__(self) -> int:
        return len(self._bars)

    def __iter__(self) -> Iterator[Bar]:
        return iter(self._bars)

    def __getitem__(self, idx: int) -> Bar:
        return self._bars[idx]

    def last(self, n: int = 1) -> list[Bar]:
        return list(self._bars)[-n:]
