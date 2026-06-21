from __future__ import annotations

from datetime import datetime, timedelta

from ict_trader.analytics.metrics import equity_curve, r_distribution, summarize
from ict_trader.clock import ET
from ict_trader.domain.enums import Killzone, Side, Symbol, TradeMode
from ict_trader.domain.trades import Trade


def _t(r: float, i: int) -> Trade:
    ts = datetime(2024, 5, 15, 10, 0, tzinfo=ET) + timedelta(minutes=i)
    return Trade(symbol=Symbol.NQ, side=Side.LONG, entry_ts=ts, entry_px=100, qty_initial=1,
                 mode=TradeMode.DEMO, exit_ts=ts + timedelta(minutes=5), exit_px=100 + r,
                 realized_pnl=r * 100, realized_r=r, killzone=Killzone.NY_AM)


def test_r_distribution_buckets():
    trades = [_t(2.1, 0), _t(2.3, 1), _t(-0.4, 2), _t(-1.2, 3)]
    rd = r_distribution(trades, bin_width=0.5)
    by = {row["bucket"]: row["count"] for row in rd}
    assert by[2.0] == 2          # 2.1 and 2.3 -> floor to 2.0
    assert by[-0.5] == 1         # -0.4 -> floor to -0.5
    assert by[-1.5] == 1         # -1.2 -> floor to -1.5
    assert sum(r["count"] for r in rd) == 4
    # buckets returned in ascending order
    assert [r["bucket"] for r in rd] == sorted(by)


def test_r_distribution_empty():
    assert r_distribution([]) == []


def test_summary_and_equity_consistent():
    trades = [_t(2.0, 0), _t(-1.0, 1), _t(1.0, 2)]
    s = summarize(trades)
    assert s["overall"]["n"] == 3
    eq = equity_curve(trades)
    assert eq[-1]["cum_r"] == 2.0   # 2 - 1 + 1
