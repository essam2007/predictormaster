from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from ict_trader.clock import ET
from ict_trader.domain.enums import BreakevenTrigger, ExitReason, Killzone, Side, Symbol, TradeMode
from ict_trader.domain.trades import Trade

# report.py lives in scripts/ (not the package); import it directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import report  # noqa: E402


def _t(r: float, be_early: bool, i: int) -> Trade:
    ts = datetime(2024, 5, 15, 10, 0, tzinfo=ET) + timedelta(days=i)
    return Trade(
        symbol=Symbol.NQ, side=Side.LONG, entry_ts=ts, entry_px=100, qty_initial=1,
        mode=TradeMode.DEMO, exit_ts=ts, exit_px=100 + r, realized_pnl=r * 100, realized_r=r,
        killzone=Killzone.SILVER_BULLET, quarter_idx=2, day_of_week=2, path_clean=True,
        moved_to_be_early=be_early,
        be_trigger=BreakevenTrigger.EARLY_PULLBACK if be_early else BreakevenTrigger.STRUCTURAL_BREAK,
        exit_reason=ExitReason.RUNNER_TARGET if r > 0 else ExitReason.BREAKEVEN)


def test_render_html_has_sections_and_bucket():
    trades = [_t(2.0, False, 0), _t(-1.0, True, 1), _t(1.5, False, 2)]
    out = report.render_html(trades, [], "demo")
    assert "<html" in out and "Overall" in out
    assert "Per-bucket" in out
    assert "moved_to_be_early" in out and "be_early" in out
    assert "Equity" in out and "<svg" in out
    assert "R distribution" in out
    assert "Trade journal (3)" in out


def test_render_html_empty():
    out = report.render_html([], [], "live")
    assert "No trades in this mode yet" in out
