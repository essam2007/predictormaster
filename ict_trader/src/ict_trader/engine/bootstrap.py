"""Build / start the live engine from settings — shared by the CLI and the hosted API.

`start_demo_engine` lets the deployed deck stream the user's Tradovate DEMO data and
paper-trade in-process (no separate worker), so the hosted URL shows live demo activity.
It is strictly opt-in, demo-only, and never crashes the API if the broker is unreachable.
"""

from __future__ import annotations

import asyncio
import logging
import os

from ..config import Settings, get_risk_settings, get_tradovate_settings
from ..execution.risk import RiskEngine
from .pipeline import SignalPipeline
from .runtime import LiveEngine

log = logging.getLogger("ict_trader.bootstrap")


def build_live_feed(settings: Settings):
    """Build the Tradovate market-data feed + a shared REST client from env creds.

    Returns (feed, rest) or (None, None) when credentials aren't configured.
    """
    import httpx

    from ..execution.tradovate_rest import TradovateCredentials, TradovateREST
    from ..marketdata.tradovate_md import TradovateMarketData

    ts = get_tradovate_settings()
    if not ts.configured:
        return None, None
    creds = TradovateCredentials(
        name=ts.name, password=ts.password, app_id=ts.app_id, app_version=ts.app_version,
        cid=ts.cid, sec=ts.secret, device_id=ts.device_id)
    rest = TradovateREST(settings.tradovate_base_url, creds,
                         client=httpx.AsyncClient(timeout=15.0))
    feed = TradovateMarketData(rest, settings.tradovate_md_ws, ts.es_symbol, ts.nq_symbol)
    return feed, rest


def build_engine(settings: Settings, *, dry_run: bool = True) -> LiveEngine:
    rs = get_risk_settings()
    risk = RiskEngine(
        per_trade_usd=rs.per_trade_usd, daily_loss_limit_usd=rs.daily_loss_limit_usd,
        max_concurrent_positions=rs.max_concurrent_positions,
        max_contracts=rs.live_max_contracts if settings.is_live else rs.max_contracts)
    return LiveEngine(pipeline=SignalPipeline(traded=settings.symbol_traded), risk=risk,
                      mode=settings.mode, dry_run=dry_run)


def attach_persistence(engine: LiveEngine, db, mode) -> None:
    """Subscribe DB sinks so the engine's setups/trades land in the store the deck reads."""
    from ..store.repositories import Repository

    async def persist_setup(snap) -> None:
        async with db.session() as s:
            await Repository(s).add_setups([snap], mode)

    async def persist_trade(trade) -> None:
        async with db.session() as s:
            await Repository(s).add_trade(trade)

    engine.bus.subscribe("setup", persist_setup)
    engine.bus.subscribe("trade", persist_trade)


def _autostart_enabled() -> bool:
    return str(os.environ.get("ICT_TRADER_ENGINE_AUTOSTART", "")).lower() in ("1", "true", "yes")


async def start_demo_engine(settings: Settings, db) -> asyncio.Task | None:
    """Opt-in: run the PAPER engine on Tradovate DEMO data as a background task.

    Returns the task, or None if not started (autostart off, live mode, or no creds).
    Any broker/connection error is logged and the task exits — the API keeps serving.
    """
    if not _autostart_enabled():
        return None
    if settings.is_live:
        log.warning("engine autostart refused in LIVE mode (demo only)")
        return None
    feed, rest = build_live_feed(settings)
    if feed is None:
        log.info("engine autostart: Tradovate creds not set — skipping (deck still serves)")
        return None
    engine = build_engine(settings, dry_run=True)
    attach_persistence(engine, db, settings.mode)

    async def _run() -> None:
        try:
            result = await rest.verify()
            if not result.get("connected"):
                log.warning("engine autostart: Tradovate connect failed: %s", result.get("error"))
                return
            log.info("engine autostart: connected account %s — streaming DEMO data (paper)",
                     result.get("account_id"))
            await engine.run(feed.stream())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("engine autostart crashed: %s", exc)
        finally:
            await rest.close()

    return asyncio.create_task(_run())
