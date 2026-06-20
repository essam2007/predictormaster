from __future__ import annotations

from datetime import datetime, timedelta

from ict_trader.backtest.sim_broker import SimBroker
from ict_trader.clock import ET
from ict_trader.domain.bars import Bar
from ict_trader.domain.enums import Side, Symbol, Timeframe, TradeMode
from ict_trader.domain.signals import EntryIntent, SetupSnapshot
from ict_trader.execution.paper_broker import PaperBroker


def _intent():
    snap = SetupSnapshot(ts=datetime(2024, 5, 15, 10, 0, tzinfo=ET), bias=Side.LONG,
                         path_clean=True, score=1.0)
    return EntryIntent(ts=snap.ts, side=Side.LONG, entry_px=100, stop_px=98, tp1_px=104,
                       tp2_px=107, runner_target_px=110, risk_r=5, setup=snap)


def _bars():
    def bar(i, o, h, low, c):
        ts = datetime(2024, 5, 15, 10, 0, tzinfo=ET) + timedelta(minutes=5 * i)
        return Bar(Symbol.NQ, Timeframe.M5, ts, o, h, low, c, volume=1.0)
    return [
        bar(1, 101, 101.5, 99.6, 100.5),   # touches entry
        bar(2, 100.5, 102, 100, 101.5),
        bar(3, 101.5, 103, 101, 102.5),
        bar(4, 102.5, 104.3, 102, 104.1),  # tp1
        bar(5, 104, 105, 103.5, 104.8),
        bar(6, 104.8, 107.3, 104.5, 107.1),  # tp2
        bar(7, 107, 108, 106.5, 107.6),
        bar(8, 107.6, 110.6, 107.2, 110.3),  # runner target
    ]


def test_paper_broker_streaming_winner():
    broker = PaperBroker(point_value=20.0, mode=TradeMode.DEMO)
    pp = broker.open(_intent(), qty=3, symbol=Symbol.NQ)
    trade = None
    for b in _bars():
        trade = broker.on_bar(pp, b)
        if pp.closed:
            break
    assert trade is not None and pp.closed
    assert trade.exit_reason.value == "runner_target"
    assert trade.realized_r > 0
    assert trade.partials_taken >= 1
    assert trade.moved_to_be_early is False


def test_streaming_matches_batch():
    """The streaming PaperBroker and the batch SimBroker must agree on the same scenario."""
    intent, bars = _intent(), _bars()
    sim = SimBroker(point_value=20.0, mode=TradeMode.BACKTEST)
    batch = sim.run_position(intent, qty=3, future_bars=bars, symbol=Symbol.NQ)

    broker = PaperBroker(point_value=20.0, mode=TradeMode.BACKTEST)
    pp = broker.open(intent, qty=3, symbol=Symbol.NQ)
    stream = None
    for b in bars:
        stream = broker.on_bar(pp, b)
        if pp.closed:
            break
    assert batch is not None and stream is not None
    assert batch.exit_reason == stream.exit_reason
    assert batch.realized_r == stream.realized_r
    assert batch.partials_taken == stream.partials_taken


def test_no_fill_when_stop_hit_before_entry():
    broker = PaperBroker(point_value=20.0)
    pp = broker.open(_intent(), qty=1, symbol=Symbol.NQ)
    # a bar that gaps straight through the stop without touching entry
    b = Bar(Symbol.NQ, Timeframe.M5, datetime(2024, 5, 15, 10, 5, tzinfo=ET),
            97.5, 97.8, 96.0, 96.5)
    broker.on_bar(pp, b)
    assert pp.dead is True and pp.trade is None
