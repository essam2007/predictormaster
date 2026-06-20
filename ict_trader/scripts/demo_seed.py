#!/usr/bin/env python
"""Seed the store with SYNTHETIC sample trades so the research deck has data to show.

These are NOT real results — they are illustrative trades generated to demonstrate the
deck's per-bucket analytics (note how the 'breakeven-early' bucket underperforms, which is
the whole point of the strategy's management fix). Run once before launching the deck:

    python scripts/demo_seed.py
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta

from ict_trader.clock import ET
from ict_trader.config import get_settings
from ict_trader.domain.enums import (
    AMDPhase,
    BreakevenTrigger,
    ExitReason,
    Killzone,
    Side,
    Symbol,
    TradeMode,
)
from ict_trader.domain.trades import Trade
from ict_trader.store.db import Database
from ict_trader.store.repositories import Repository

_DOW = [1, 2, 3, 4]  # Tue..Fri
_KZ = [Killzone.NY_AM, Killzone.SILVER_BULLET]


def _sample_trades(n: int = 60, seed: int = 7) -> list[Trade]:
    rng = random.Random(seed)
    trades: list[Trade] = []
    base = datetime(2024, 5, 1, 10, 0, tzinfo=ET)
    for i in range(n):
        early_be = rng.random() < 0.4
        clean = rng.random() < 0.6
        # Edge model: clean path + no early-breakeven => better R. This mirrors the
        # documented flaw so the deck's buckets tell the real story.
        mean_r = 1.4 if clean else 0.2
        if early_be:
            mean_r -= 1.0  # capping the runner early collapses expectancy
        r = round(rng.gauss(mean_r, 1.1), 2)
        won = r > 0
        ts = base + timedelta(days=i, minutes=rng.randint(0, 50))
        side = Side.LONG if rng.random() < 0.5 else Side.SHORT
        reason = (ExitReason.RUNNER_TARGET if (won and not early_be)
                  else ExitReason.BREAKEVEN if early_be else ExitReason.STOP)
        trades.append(Trade(
            symbol=Symbol.NQ, side=side, entry_ts=ts, entry_px=18000 + i,
            qty_initial=2, mode=TradeMode.BACKTEST,
            exit_ts=ts + timedelta(minutes=35), exit_px=18000 + i + r,
            realized_pnl=round(r * 200, 2), realized_r=r,
            mae_r=round(-abs(rng.gauss(0.5, 0.3)), 2), mfe_r=round(abs(r) + 0.5, 2),
            day_of_week=rng.choice(_DOW), killzone=rng.choice(_KZ),
            quarter_idx=rng.choice([2, 3]), amd_phase=AMDPhase.DISTRIBUTION,
            daily_extreme_in=rng.random() < 0.3, path_clean=clean,
            moved_to_be_early=early_be,
            be_trigger=BreakevenTrigger.EARLY_PULLBACK if early_be else BreakevenTrigger.STRUCTURAL_BREAK,
            partials_taken=rng.randint(0, 2), runner_held=not early_be,
            runner_hit_erl=(reason is ExitReason.RUNNER_TARGET), exit_reason=reason,
            setup_score=round(rng.uniform(0.5, 1.0), 2),
        ))
    return trades


async def _run() -> None:
    s = get_settings()
    db = Database(s.db_url)
    await db.create_all()
    trades = _sample_trades()
    async with db.session() as sess:
        await Repository(sess).add_trades(trades)
    await db.dispose()
    print(f"seeded {len(trades)} SAMPLE trades into {s.db_url} (mode=backtest). "
          f"Open the deck and view the Per-Bucket Analytics tab.")


if __name__ == "__main__":
    asyncio.run(_run())
