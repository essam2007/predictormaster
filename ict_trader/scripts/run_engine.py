#!/usr/bin/env python
"""Start the live/demo engine.

Phase 2 (paper): runs the pipeline against a feed in DRY-RUN — computes setups and pushes
them to the research deck, but places no orders. Wiring a TradovateREST executor and
clearing ``dry_run`` (Phase 3) arms execution on the demo endpoint first.

Usage:
    python scripts/run_engine.py --replay-es es.csv --replay-nq nq.csv   # paper over CSV
    python scripts/run_engine.py                                         # live feed (TODO)
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from ict_trader.config import get_risk_settings, get_settings
from ict_trader.engine.pipeline import SignalPipeline
from ict_trader.engine.runtime import LiveEngine
from ict_trader.execution.risk import RiskEngine
from ict_trader.marketdata.replay import CsvReplayFeed


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    rs = get_risk_settings()
    risk = RiskEngine(
        per_trade_usd=rs.per_trade_usd,
        daily_loss_limit_usd=rs.daily_loss_limit_usd,
        max_concurrent_positions=rs.max_concurrent_positions,
        max_contracts=rs.live_max_contracts if settings.is_live else rs.max_contracts,
    )
    engine = LiveEngine(
        pipeline=SignalPipeline(traded=settings.symbol_traded),
        risk=risk,
        mode=settings.mode,
        dry_run=not args.arm,
    )
    await _wire_persistence(engine, settings)
    if args.replay_es and args.replay_nq:
        feed = CsvReplayFeed(args.replay_es, args.replay_nq)
        await engine.run(feed.stream())
    else:
        raise SystemExit("Live market-data feed wiring is a Phase-3 task; use --replay-* for paper.")


async def _wire_persistence(engine, settings) -> None:
    """Subscribe DB sinks so paper setups/trades land in the store the deck reads from.

    No-ops (with a warning) if the [serve] extra isn't installed.
    """
    try:
        from ict_trader.store.db import Database
        from ict_trader.store.repositories import Repository
    except ImportError:
        logging.warning("store unavailable (install .[serve]); running without persistence")
        return

    db = Database(settings.db_url)
    await db.create_all()

    async def persist_setup(snap) -> None:
        async with db.session() as s:
            await Repository(s).add_setups([snap], settings.mode)

    async def persist_trade(trade) -> None:
        async with db.session() as s:
            await Repository(s).add_trade(trade)

    engine.bus.subscribe("setup", persist_setup)
    engine.bus.subscribe("trade", persist_trade)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--replay-es")
    p.add_argument("--replay-nq")
    p.add_argument("--arm", action="store_true",
                   help="DANGER: clear dry-run and place orders via the configured executor")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
