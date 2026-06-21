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
from datetime import UTC, datetime, timedelta

from ict_trader.analytics.trade_analyzer import analyze_trade
from ict_trader.clock import ET
from ict_trader.config import get_settings
from ict_trader.domain.bars import Bar
from ict_trader.domain.enums import (
    AMDPhase,
    BreakevenTrigger,
    ExitReason,
    Killzone,
    Side,
    Symbol,
    Timeframe,
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


def _sample_bars(n: int = 360, seed: int = 11) -> list[dict]:
    """A synthetic NQ 5-minute candle series (random walk) so the Charts tab renders real
    candlesticks before any TradingView webhook bars arrive. Illustrative, not real data."""
    rng = random.Random(seed)
    start = datetime(2024, 5, 15, 13, 30, tzinfo=UTC)  # ~NY open in UTC
    px = 18000.0
    bars: list[dict] = []
    for i in range(n):
        drift = rng.gauss(0, 6) + (4 if 40 < i < 90 else -3 if 200 < i < 250 else 0)
        o = px
        c = px + drift
        h = max(o, c) + abs(rng.gauss(0, 3))
        low = min(o, c) - abs(rng.gauss(0, 3))
        bars.append({"ts": start + timedelta(minutes=5 * i), "open": round(o, 2),
                     "high": round(h, 2), "low": round(low, 2), "close": round(c, 2),
                     "volume": rng.randint(400, 1800)})
        px = c
    return bars


def _sample_demo_trades(bars: list[dict], seed: int = 5) -> list[Trade]:
    """A few demo trades whose entry/exit land on seeded bars, so the chart shows long/short
    arrows and the demo journal isn't empty on first boot."""
    rng = random.Random(seed)
    trades: list[Trade] = []
    for _ in range(6):
        i = rng.randint(5, len(bars) - 12)
        entry, exit_ = bars[i], bars[i + rng.randint(4, 10)]
        side = Side.LONG if exit_["close"] >= entry["close"] else Side.SHORT
        move = exit_["close"] - entry["close"]
        r = round((move if side is Side.LONG else -move) / 25.0, 2)
        early_be = rng.random() < 0.4
        if early_be:
            r = min(r, 0.2)
        trades.append(Trade(
            symbol=Symbol.NQ, side=side, entry_ts=entry["ts"], entry_px=entry["open"],
            qty_initial=1, mode=TradeMode.DEMO, exit_ts=exit_["ts"], exit_px=exit_["close"],
            realized_pnl=round(r * 200, 2), realized_r=r,
            day_of_week=entry["ts"].weekday(), killzone=rng.choice(_KZ),
            quarter_idx=rng.choice([2, 3]), amd_phase=AMDPhase.DISTRIBUTION,
            path_clean=rng.random() < 0.6, moved_to_be_early=early_be,
            be_trigger=BreakevenTrigger.EARLY_PULLBACK if early_be else BreakevenTrigger.STRUCTURAL_BREAK,
            runner_held=not early_be,
            exit_reason=ExitReason.RUNNER_TARGET if (r > 0 and not early_be) else
                        ExitReason.BREAKEVEN if early_be else ExitReason.STOP,
            setup_score=round(rng.uniform(0.5, 1.0), 2)))
    return trades


async def _run() -> None:
    s = get_settings()
    db = Database(s.db_url)
    await db.create_all()
    trades = _sample_trades()
    bars = _sample_bars()
    demo_trades = _sample_demo_trades(bars)
    domain_bars = [
        Bar(symbol=Symbol.NQ, timeframe=Timeframe.M5, ts_open=b["ts"], open=b["open"],
            high=b["high"], low=b["low"], close=b["close"], volume=b["volume"])
        for b in bars
    ]
    async with db.session() as sess:
        repo = Repository(sess)
        await repo.add_trades(trades)
        await repo.add_bars("demo", "NQ", "5", bars)
        # log demo trades individually so we get ids, then auto-grade each (the AI detector)
        for t in demo_trades:
            tid = await repo.add_trade(t)
            analysis = analyze_trade(
                side=t.side, entry_ts=t.entry_ts, bars=domain_bars, killzone=t.killzone,
                path_clean=t.path_clean, moved_to_be_early=t.moved_to_be_early)
            await repo.save_trade_analysis(tid, "demo", analysis.to_dict())
    await db.dispose()
    print(f"seeded {len(trades)} backtest + {len(demo_trades)} graded demo SAMPLE trades and "
          f"{len(bars)} demo bars into {s.db_url}. Open the deck (Charts / Analytics tabs).")


if __name__ == "__main__":
    asyncio.run(_run())
