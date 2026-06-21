from __future__ import annotations

from datetime import datetime

from ict_trader.clock import ET
from ict_trader.domain.bars import Bar
from ict_trader.domain.enums import Side, Symbol, Timeframe
from ict_trader.domain.signals import EntryIntent, SetupSnapshot
from ict_trader.engine.pipeline import SignalPipeline
from ict_trader.engine.runtime import LiveEngine
from ict_trader.execution.risk import RiskEngine


def test_risk_release_open():
    r = RiskEngine(max_concurrent_positions=1)
    r.on_open()
    assert r.can_enter()[0] is False
    r.release_open()
    assert r.open_positions == 0 and r.can_enter()[0] is True


async def test_unfilled_entry_releases_the_slot():
    """Regression: an intent that never fills must not leak the concurrency slot."""
    engine = LiveEngine(pipeline=SignalPipeline(traded=Symbol.NQ),
                        risk=RiskEngine(max_concurrent_positions=1), dry_run=True)
    snap = SetupSnapshot(ts=datetime(2024, 5, 15, 10, 0, tzinfo=ET), bias=Side.LONG)
    intent = EntryIntent(ts=snap.ts, side=Side.LONG, entry_px=100, stop_px=98, tp1_px=104,
                         tp2_px=107, runner_target_px=110, risk_r=5, setup=snap)

    # reserve a paper position exactly as _handle_intent would
    engine._open = engine._broker.open(intent, qty=1, symbol=Symbol.NQ)
    engine.risk.on_open()
    assert engine.risk.open_positions == 1

    # a bar that gaps THROUGH the stop without ever touching the entry -> never fills (dead)
    bar = Bar(Symbol.NQ, Timeframe.M5, datetime(2024, 5, 15, 10, 5, tzinfo=ET),
              97, 97.5, 96, 96.5)
    await engine._advance(bar)

    assert engine._open is None
    assert engine.risk.open_positions == 0       # slot released
    assert engine.risk.can_enter()[0] is True     # engine can take the next trade
