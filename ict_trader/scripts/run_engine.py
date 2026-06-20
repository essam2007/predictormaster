#!/usr/bin/env python
"""Start the live/demo engine.

By default it runs in PAPER (dry-run): it computes setups, simulates fills, manages each
position (partials, runner-to-ERL, corrected breakeven) and persists everything to the
research deck — but places NO orders. Data comes from your connected Tradovate account
(demo unless ICT_TRADER_MODE=live) or from CSV replay.

Usage:
    python scripts/run_engine.py                       # PAPER on live Tradovate data
    python scripts/run_engine.py --replay-es es.csv --replay-nq nq.csv   # PAPER on CSV
    python scripts/run_engine.py --arm                 # place orders (demo endpoint first)

Requires TRADOVATE_* in .env for the live feed (the API Access add-on must be enabled).
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

log = logging.getLogger("ict_trader.run_engine")


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
        log.info("PAPER over CSV replay")
        feed = CsvReplayFeed(args.replay_es, args.replay_nq)
        await engine.run(feed.stream())
        return

    # --- live Tradovate feed (your account) ---
    feed, rest = _build_live_feed(settings)
    result = await rest.verify()
    if not result.get("connected"):
        await rest.close()
        raise SystemExit(f"Tradovate connection failed: {result.get('error')}. "
                         "Check TRADOVATE_* in .env (API Access add-on required).")
    log.info("connected to Tradovate account %s (%s)", result.get("account_id"),
             settings.tradovate_base_url)
    if args.arm:
        engine.executor = rest
        engine.dry_run = False
        log.warning("EXECUTION ARMED on %s — orders WILL be placed (%s)",
                    settings.mode.value, settings.tradovate_base_url)
    else:
        log.info("PAPER mode — streaming your account's data, placing NO orders")
    try:
        await engine.run(feed.stream())
    finally:
        await rest.close()


def _build_live_feed(settings):
    """Build the Tradovate market-data feed + a shared REST client from env creds."""
    import httpx

    from ict_trader.config import get_tradovate_settings
    from ict_trader.execution.tradovate_rest import TradovateCredentials, TradovateREST
    from ict_trader.marketdata.tradovate_md import TradovateMarketData

    ts = get_tradovate_settings()
    if not ts.configured:
        raise SystemExit("Tradovate credentials not set — fill TRADOVATE_* in .env "
                         "(or use --replay-es/--replay-nq for CSV).")
    creds = TradovateCredentials(
        name=ts.name, password=ts.password, app_id=ts.app_id, app_version=ts.app_version,
        cid=ts.cid, sec=ts.secret, device_id=ts.device_id)
    rest = TradovateREST(settings.tradovate_base_url, creds,
                         client=httpx.AsyncClient(timeout=15.0))
    feed = TradovateMarketData(rest, settings.tradovate_md_ws, ts.es_symbol, ts.nq_symbol)
    return feed, rest


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
