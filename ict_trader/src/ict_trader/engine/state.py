"""Rolling market state: per-symbol multi-timeframe series, co-bar sync, liquidity."""

from __future__ import annotations

from datetime import datetime

from ..clock import ET
from ..detectors.liquidity import LiquidityState
from ..domain.bars import Bar, CoBar, Series
from ..domain.enums import Symbol, Timeframe
from ..marketdata.bar_builder import MultiTimeframeBuilder
from ..marketdata.sync import CoBarSync


class MarketState:
    def __init__(self, symbols: tuple[Symbol, ...] = (Symbol.ES, Symbol.NQ)) -> None:
        self.symbols = symbols
        self.builders = {s: MultiTimeframeBuilder(s) for s in symbols}
        self.series: dict[tuple[Symbol, Timeframe], Series] = {}
        self.cobars: dict[Timeframe, list[CoBar]] = {}
        self.sync = CoBarSync()
        self.liquidity = {s: LiquidityState() for s in symbols}
        self.last_ts: datetime | None = None

    def _series(self, symbol: Symbol, tf: Timeframe) -> Series:
        key = (symbol, tf)
        if key not in self.series:
            self.series[key] = Series(symbol, tf)
        return self.series[key]

    def on_minute_bar(self, m1: Bar) -> dict[Timeframe, Bar]:
        """Ingest a closed 1-minute bar; update all series + liquidity + co-bars.

        Returns the map of timeframes that closed a bar on this minute.
        """
        self.last_ts = m1.ts_open
        et_date = m1.ts_open.astimezone(ET).date()
        self.liquidity[m1.symbol].update(m1, et_date)

        closed = self.builders[m1.symbol].add(m1)
        for tf, bar in closed.items():
            self._series(bar.symbol, tf).append(bar)
            if tf is not Timeframe.M1:
                cobar = self.sync.add(bar)
                if cobar is not None:
                    self.cobars.setdefault(tf, []).append(cobar)
        return closed

    def closed_bars(self, symbol: Symbol, tf: Timeframe) -> list[Bar]:
        s = self.series.get((symbol, tf))
        return s.closed if s else []

    def latest_cobar(self, tf: Timeframe) -> CoBar | None:
        lst = self.cobars.get(tf)
        return lst[-1] if lst else None


def align_closed(es: list[Bar], nq: list[Bar]) -> tuple[list[Bar], list[Bar]]:
    """Return ES/NQ closed bars restricted to their common timestamps, in order."""
    nq_by_ts = {b.ts_open: b for b in nq}
    out_es: list[Bar] = []
    out_nq: list[Bar] = []
    for b in es:
        match = nq_by_ts.get(b.ts_open)
        if match is not None:
            out_es.append(b)
            out_nq.append(match)
    return out_es, out_nq
