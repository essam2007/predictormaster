from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("sqlalchemy", reason="requires the [serve] extra")

from ict_trader.analytics.metrics import summarize  # noqa: E402
from ict_trader.clock import ET  # noqa: E402
from ict_trader.domain.enums import (  # noqa: E402
    ExitReason,
    Killzone,
    Side,
    Symbol,
    TradeMode,
)
from ict_trader.domain.trades import Trade  # noqa: E402
from ict_trader.store.db import Database  # noqa: E402
from ict_trader.store.repositories import Repository  # noqa: E402


def _trade(r: float, pnl: float) -> Trade:
    return Trade(
        symbol=Symbol.NQ, side=Side.LONG, entry_ts=datetime(2024, 5, 15, 10, 0, tzinfo=ET),
        entry_px=100, qty_initial=2, mode=TradeMode.BACKTEST,
        exit_ts=datetime(2024, 5, 15, 10, 30, tzinfo=ET), exit_px=100 + r,
        realized_pnl=pnl, realized_r=r, killzone=Killzone.SILVER_BULLET, quarter_idx=2,
        day_of_week=2, path_clean=True, exit_reason=ExitReason.RUNNER_TARGET,
    )


async def test_trade_roundtrip_and_analytics():
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.create_all()
    async with db.session() as s:
        repo = Repository(s)
        await repo.add_trades([_trade(2.0, 200), _trade(-1.0, -100), _trade(3.0, 300)])
        loaded = await repo.list_trades(TradeMode.BACKTEST)
    assert len(loaded) == 3
    report = summarize(loaded)
    assert report["overall"]["n"] == 3
    assert report["overall"]["hit_rate"] == pytest.approx(2 / 3, abs=0.01)
    # bucket breakdown present for the path_clean dimension
    assert any(b["label"] == "clean" for b in report["buckets"]["path_clean"])
    await db.dispose()
