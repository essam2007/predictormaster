from __future__ import annotations

from datetime import datetime, timedelta

from ict_trader.analytics.calibration import component_lift, score_reliability
from ict_trader.analytics.metrics import equity_curve, summarize
from ict_trader.backtest.harness import Backtester
from ict_trader.backtest.sim_broker import SimBroker
from ict_trader.clock import ET
from ict_trader.domain.bars import Bar
from ict_trader.domain.enums import Side, Symbol, Timeframe, TradeMode
from ict_trader.domain.signals import EntryIntent, SetupSnapshot
from ict_trader.marketdata.replay import MemoryReplayFeed


def _synthetic_session() -> list[Bar]:
    """A NY-AM Wednesday: drift down into 09:50, then reversal up. ES dips a touch lower
    than NQ at the low (bullish SMT flavour). Returns interleaved 1m bars for ES + NQ."""
    start = datetime(2024, 5, 15, 7, 0, tzinfo=ET)  # Wed, inside NY-AM killzone
    bars: list[Bar] = []
    n = 240  # 4 hours of 1m bars
    for i in range(n):
        ts = start + timedelta(minutes=i)
        # V-shape: down for first 170 min, up after
        if i < 170:
            base = 100.0 - i * 0.05
        else:
            base = 100.0 - 170 * 0.05 + (i - 170) * 0.12
        for sym, jitter in ((Symbol.NQ, 0.0), (Symbol.ES, -0.02 if 150 <= i <= 175 else 0.0)):
            o = base + jitter
            c = base + jitter + (0.03 if i >= 170 else -0.03)
            h = max(o, c) + 0.05
            low = min(o, c) - 0.05
            bars.append(Bar(sym, Timeframe.M1, ts, o, h, low, c, volume=10.0))
    return bars


def test_backtester_runs_end_to_end():
    feed = MemoryReplayFeed(_synthetic_session())
    bt = Backtester(feed, traded=Symbol.NQ)
    res = bt.run()
    # The engine must run without error and record setup snapshots for every evaluation.
    assert len(res.setups) > 0
    # Analytics must be computable regardless of how many trades fired.
    report = summarize(res.trades)
    assert "overall" in report and "buckets" in report
    assert isinstance(equity_curve(res.trades), list)
    assert isinstance(component_lift(res.trades, res.setups), dict)
    assert isinstance(score_reliability(res.trades), list)
    # Every recorded setup carries the analysis dimensions used by the research deck.
    s = res.setups[0]
    assert hasattr(s, "killzone") and hasattr(s, "quarter_idx")


def test_sim_broker_full_winning_position():
    """Hand-built A+ long: entry filled, partials taken, runner exits at ERL with +R."""
    snap = SetupSnapshot(ts=datetime(2024, 5, 15, 10, 0, tzinfo=ET), bias=Side.LONG,
                         path_clean=True, score=1.0)
    intent = EntryIntent(ts=snap.ts, side=Side.LONG, entry_px=100, stop_px=98,
                         tp1_px=104, tp2_px=107, runner_target_px=110, risk_r=5, setup=snap)

    def bar(i, o, h, low, c):
        ts = datetime(2024, 5, 15, 10, 0, tzinfo=ET) + timedelta(minutes=5 * i)
        return Bar(Symbol.NQ, Timeframe.M5, ts, o, h, low, c, volume=1.0)

    future = [
        bar(1, 101, 101.5, 99.6, 100.5),   # touches entry 100
        bar(2, 100.5, 102, 100, 101.5),
        bar(3, 101.5, 103, 101, 102.5),
        bar(4, 102.5, 104.3, 102, 104.1),  # tp1 partial (>=104)
        bar(5, 104, 105, 103.5, 104.8),
        bar(6, 104.8, 107.3, 104.5, 107.1),  # tp2 partial (>=107)
        bar(7, 107, 108, 106.5, 107.6),
        bar(8, 107.6, 110.6, 107.2, 110.3),  # runner target 110 -> exit
    ]
    broker = SimBroker(point_value=20.0, mode=TradeMode.BACKTEST)
    trade = broker.run_position(intent, qty=3, future_bars=future, symbol=Symbol.NQ)
    assert trade is not None
    assert trade.exit_reason.value == "runner_target"
    assert trade.realized_r > 0
    assert trade.partials_taken >= 1
    assert trade.moved_to_be_early is False  # corrected logic never trips early BE
