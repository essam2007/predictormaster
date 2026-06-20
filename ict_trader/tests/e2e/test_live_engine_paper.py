from __future__ import annotations

from datetime import datetime, timedelta

from ict_trader.clock import ET
from ict_trader.domain.bars import Bar
from ict_trader.domain.enums import Symbol, Timeframe
from ict_trader.engine.pipeline import SignalPipeline
from ict_trader.engine.runtime import LiveEngine
from ict_trader.execution.risk import RiskEngine
from ict_trader.marketdata.replay import MemoryReplayFeed


def _session() -> list[Bar]:
    start = datetime(2024, 5, 15, 7, 0, tzinfo=ET)
    bars: list[Bar] = []
    for i in range(240):
        ts = start + timedelta(minutes=i)
        base = (100.0 - i * 0.05) if i < 170 else (100.0 - 170 * 0.05 + (i - 170) * 0.12)
        for sym, jit in ((Symbol.NQ, 0.0), (Symbol.ES, -0.02 if 150 <= i <= 175 else 0.0)):
            o = base + jit
            c = base + jit + (0.03 if i >= 170 else -0.03)
            bars.append(Bar(sym, Timeframe.M1, ts, o, max(o, c) + 0.05, min(o, c) - 0.05, c, 10.0))
    return bars


async def test_live_engine_paper_loop_runs():
    feed = MemoryReplayFeed(_session())
    engine = LiveEngine(pipeline=SignalPipeline(traded=Symbol.NQ), risk=RiskEngine(),
                        dry_run=True)
    trades_via_bus: list = []
    setups_via_bus: list = []
    engine.bus.subscribe("trade", lambda t: _collect(trades_via_bus, t))
    engine.bus.subscribe("setup", lambda s: _collect(setups_via_bus, s))

    await engine.run(feed.stream())

    # The paper loop must run end-to-end and evaluate setups on every trigger close.
    assert engine.setups_seen > 0
    assert len(setups_via_bus) == engine.setups_seen
    # Any trades produced must be coherent and never trip the early-breakeven flaw.
    for t in engine.closed_trades:
        assert t.moved_to_be_early is False
        assert t.exit_reason is not None


async def _collect(sink: list, item) -> None:
    sink.append(item)
