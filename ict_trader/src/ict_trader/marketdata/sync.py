"""Pair ES and NQ bars into time-aligned co-bars.

If one feed's bar is missing/late within the buffer the co-bar is marked degraded; SMT and
PSP detectors refuse to fire on degraded co-bars so we never fabricate a divergence on
unsynced data.
"""

from __future__ import annotations

from ..domain.bars import Bar, CoBar
from ..domain.enums import Symbol, Timeframe


class CoBarSync:
    """Buffers closed bars per (timeframe) and emits a CoBar when both sides arrive."""

    def __init__(self) -> None:
        # (timeframe, ts) -> {symbol: bar}
        self._pending: dict[tuple[Timeframe, object], dict[Symbol, Bar]] = {}

    def add(self, bar: Bar) -> CoBar | None:
        key = (bar.timeframe, bar.ts_open)
        slot = self._pending.setdefault(key, {})
        slot[bar.symbol] = bar
        if Symbol.ES in slot and Symbol.NQ in slot:
            del self._pending[key]
            return CoBar(ts_open=bar.ts_open, timeframe=bar.timeframe,
                         es=slot[Symbol.ES], nq=slot[Symbol.NQ])
        return None

    def flush_degraded(self, before_ts: object, timeframe: Timeframe) -> list[CoBar]:
        """Emit degraded co-bars for periods that never completed before ``before_ts``."""
        out: list[CoBar] = []
        for key in list(self._pending):
            tf, ts = key
            if tf is timeframe and ts < before_ts:  # type: ignore[operator]
                slot = self._pending.pop(key)
                out.append(CoBar(ts_open=ts, timeframe=tf,  # type: ignore[arg-type]
                                 es=slot.get(Symbol.ES), nq=slot.get(Symbol.NQ)))
        return out
