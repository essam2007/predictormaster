from __future__ import annotations

from tests.conftest import mk_bar

from ict_trader.domain.enums import Symbol, Timeframe
from ict_trader.marketdata.bar_builder import TimeframeAggregator, period_start
from ict_trader.marketdata.sync import CoBarSync


def _m1(i, o, h, low, c, symbol=Symbol.NQ):
    return mk_bar(i, o, h, low, c, symbol=symbol, timeframe=Timeframe.M1,
                  start=mk_bar(0, 0, 0, 0, 0).ts_open.replace(hour=9, minute=0))


def test_period_start_alignment():
    b = mk_bar(0, 1, 1, 1, 1, timeframe=Timeframe.M1)  # 09:00 ET
    assert period_start(b.ts_open, Timeframe.M5).minute == 0
    b3 = mk_bar(7, 1, 1, 1, 1, timeframe=Timeframe.M1)  # 09:07
    assert period_start(b3.ts_open, Timeframe.M5).minute == 5


def test_aggregator_emits_closed_5m():
    agg = TimeframeAggregator(Symbol.NQ, Timeframe.M5)
    bars = [
        _m1(0, 10, 12, 9, 11),   # 09:00
        _m1(1, 11, 13, 10, 12),  # 09:01
        _m1(2, 12, 14, 11, 13),  # 09:02
        _m1(3, 13, 13.5, 12, 12.5),  # 09:03
        _m1(4, 12.5, 12.6, 11.5, 12),  # 09:04
        _m1(5, 12, 12, 11, 11.5),  # 09:05 -> rolls the 09:00 5m bar
    ]
    emitted = [agg.add(b) for b in bars]
    assert all(e is None for e in emitted[:5])
    closed = emitted[5]
    assert closed is not None
    assert closed.open == 10 and closed.high == 14 and closed.low == 9 and closed.close == 12
    assert closed.ts_open.minute == 0


def test_cobar_sync_pairs_es_nq():
    sync = CoBarSync()
    es = mk_bar(0, 1, 2, 0.5, 1.5, symbol=Symbol.ES, timeframe=Timeframe.M5)
    nq = mk_bar(0, 1, 2, 0.5, 1.5, symbol=Symbol.NQ, timeframe=Timeframe.M5)
    assert sync.add(es) is None  # waiting for NQ
    cobar = sync.add(nq)
    assert cobar is not None and not cobar.degraded
    assert cobar.es is es and cobar.nq is nq
