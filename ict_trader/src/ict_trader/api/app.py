"""FastAPI research-deck backend.

Read-mostly views over the store (per-bucket analytics, trade journal, equity) plus a
guarded control surface (kill switch) and the Pine webhook receiver. The frontend renders
these; nothing here can place an order (the live engine owns execution).
"""

from __future__ import annotations

import asyncio
import hmac
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..analytics.calibration import component_lift, score_reliability
from ..analytics.metrics import equity_curve, summarize
from ..config import Settings, get_settings
from ..domain.enums import (
    AMDPhase,
    BreakevenTrigger,
    ExitReason,
    Killzone,
    Side,
    Symbol,
    TradeMode,
)
from ..domain.trades import Trade
from ..execution.kill_switch import KillSwitch
from ..execution.risk import RiskEngine
from ..store.db import Database
from ..store.repositories import Repository
from .ws import LiveHub


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.db_url)
        self.kill = KillSwitch()
        self.risk = RiskEngine()
        self.hub = LiveHub()
        # background demo engine task (set in lifespan if configured)
        self.engine_task: asyncio.Task | None = None


def _require_control(state: AppState, authorization: str | None) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    expected = state.settings.control_token
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="control token required")


def _enum(enum_cls: Any, value: Any, default: Any) -> Any:
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        return default


def _make_trade(
    *,
    side: str,
    realized_r: float,
    mode: str,
    killzone: str,
    quarter_idx: int,
    day_of_week: int,
    path_clean: bool,
    moved_to_be_early: bool,
    exit_reason: str,
    entry_px: float = 0.0,
    exit_px: float | None = None,
    realized_pnl: float | None = None,
) -> Trade:
    """Build a realized Trade from journaled/webhook fields (shared by both sources)."""
    now = datetime.now(UTC)
    dow = day_of_week if day_of_week >= 0 else now.weekday()
    be = (
        BreakevenTrigger.EARLY_PULLBACK
        if moved_to_be_early
        else BreakevenTrigger.STRUCTURAL_BREAK
    )
    return Trade(
        symbol=Symbol.NQ,
        side=_enum(Side, side, Side.LONG),
        entry_ts=now,
        entry_px=entry_px,
        qty_initial=1,
        mode=_enum(TradeMode, mode, TradeMode.DEMO),
        exit_ts=now,
        exit_px=exit_px,
        realized_pnl=realized_pnl if realized_pnl is not None else round(realized_r * 100, 2),
        realized_r=realized_r,
        day_of_week=dow,
        killzone=_enum(Killzone, killzone, Killzone.NY_AM),
        quarter_idx=quarter_idx,
        amd_phase=AMDPhase.DISTRIBUTION,
        path_clean=path_clean,
        moved_to_be_early=moved_to_be_early,
        be_trigger=be,
        runner_held=not moved_to_be_early,
        exit_reason=_enum(ExitReason, exit_reason, ExitReason.TP),
    )


class BacktestRequest(BaseModel):
    es_csv: str
    nq_csv: str
    traded: str = "NQ"
    slippage: float = 0.25


class LogTradeRequest(BaseModel):
    """A manually-journaled trade (e.g. a TradingView Paper-Trading fill)."""

    side: str = "long"
    realized_r: float
    realized_pnl: float | None = None
    killzone: str = "ny_am"
    day_of_week: int = -1
    quarter_idx: int = -1
    path_clean: bool = True
    moved_to_be_early: bool = False
    exit_reason: str = "tp"
    entry_px: float = 0.0
    exit_px: float | None = None
    note: str = ""
    mode: str = "demo"


class PineAlert(BaseModel):
    source: str = "pine"
    secret: str | None = None
    kind: str = "signal"  # "signal" (a setup) or "trade" (a closed round-trip from a strategy)
    symbol: str | None = None
    bias: str | None = None
    components: dict[str, Any] = {}
    killzone: str | None = None
    quarter: int | None = None
    amd: str | None = None
    entry: float | None = None
    stop: float | None = None
    erl_target: float | None = None
    # trade-event fields (kind == "trade"): a TradingView strategy posts these on each fill
    # so the per-condition analytics accrue with no broker API.
    side: str | None = None
    exit: float | None = None
    realized_r: float | None = None
    exit_reason: str | None = None
    moved_to_be_early: bool = False
    path_clean: bool = True
    day_of_week: int = -1
    note: str = ""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        from ..engine.bootstrap import start_demo_engine

        await state.db.create_all()
        # Optionally stream the user's Tradovate DEMO data + paper-trade in-process
        # (opt-in via ICT_TRADER_ENGINE_AUTOSTART; no-op without creds).
        state.engine_task = await start_demo_engine(state.settings, state.db)
        yield
        if state.engine_task is not None:
            state.engine_task.cancel()
        await state.db.dispose()

    app = FastAPI(title="ict-trader research deck", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.state.ict = state

    def get_state() -> AppState:
        return state

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "mode": settings.mode.value}

    @app.get("/api/status")
    async def status(st: AppState = Depends(get_state)) -> dict:
        engine_running = st.engine_task is not None and not st.engine_task.done()
        return {
            "mode": st.settings.mode.value,
            "is_live": st.settings.is_live,
            "engine_running": engine_running,
            "kill_switch": {"active": st.kill.active, "reason": st.kill.reason},
            "risk": {
                "daily_loss_used": st.risk.daily_loss_used,
                "daily_loss_limit": st.risk.daily_loss_limit_usd,
                "open_positions": st.risk.open_positions,
                "halted": st.risk.halted,
            },
        }

    @app.get("/api/analytics/summary")
    async def analytics_summary(mode: str = "backtest", st: AppState = Depends(get_state)) -> dict:
        async with st.db.session() as s:
            trades = await Repository(s).list_trades(TradeMode(mode))
        return summarize(trades)

    @app.get("/api/analytics/equity")
    async def analytics_equity(mode: str = "backtest", st: AppState = Depends(get_state)) -> list:
        async with st.db.session() as s:
            trades = await Repository(s).list_trades(TradeMode(mode))
        return equity_curve(trades)

    @app.get("/api/analytics/calibration")
    async def analytics_calibration(mode: str = "backtest",
                                    st: AppState = Depends(get_state)) -> dict:
        async with st.db.session() as s:
            repo = Repository(s)
            trades = await repo.list_trades(TradeMode(mode))
            setup_rows = await repo.list_setups(TradeMode(mode))
        from ..domain.enums import AMDPhase, Killzone, Side
        from ..domain.signals import SetupSnapshot
        setups = [
            SetupSnapshot(
                ts=r.ts, bias=Side(r.bias), fvg_ok=r.fvg_ok, smt1_ok=r.smt1_ok,
                smt2_ok=r.smt2_ok, psp_ok=r.psp_ok, ltf_trigger_ok=r.ltf_trigger_ok,
                lrlr_ok=r.lrlr_ok, timing_ok=r.timing_ok, dayfilter_ok=r.dayfilter_ok,
                management_ok=r.management_ok, daily_extreme_in=r.daily_extreme_in,
                path_clean=r.path_clean, killzone=Killzone(r.killzone),
                quarter_idx=r.quarter_idx, amd_phase=AMDPhase(r.amd_phase),
                score=r.score, gated_pass=r.gated_pass,
            ) for r in setup_rows
        ]
        return {"component_lift": component_lift(trades, setups),
                "score_reliability": score_reliability(trades)}

    @app.get("/api/trades")
    async def list_trades(mode: str = "backtest", limit: int = 500,
                          st: AppState = Depends(get_state)) -> list:
        async with st.db.session() as s:
            trades = await Repository(s).list_trades(TradeMode(mode))
        return [
            {
                "entry_ts": t.entry_ts.isoformat(), "side": t.side.value,
                "entry_px": t.entry_px, "exit_px": t.exit_px,
                "realized_r": t.realized_r, "realized_pnl": t.realized_pnl,
                "killzone": t.killzone.value, "quarter_idx": t.quarter_idx,
                "day_of_week": t.day_of_week, "path_clean": t.path_clean,
                "moved_to_be_early": t.moved_to_be_early,
                "exit_reason": t.exit_reason.value if t.exit_reason else None,
            }
            for t in trades[:limit]
        ]

    @app.get("/api/webhooks")
    async def list_webhooks(limit: int = 100, st: AppState = Depends(get_state)) -> list:
        """Recent TradingView alerts that landed on /webhooks/pine (signals + trades)."""
        async with st.db.session() as s:
            rows = await Repository(s).list_webhooks(limit)
        return [{"ts": r.ts.isoformat(), "matched": r.matched, **r.payload} for r in rows]

    @app.post("/api/backtest")
    async def run_backtest(req: BacktestRequest, authorization: str | None = Header(default=None),
                           st: AppState = Depends(get_state)) -> dict:
        # reads CSV paths from the server FS -> require the control token (matters once hosted)
        _require_control(st, authorization)
        import anyio

        from ..backtest.harness import Backtester
        from ..marketdata.replay import CsvReplayFeed

        def _run():
            feed = CsvReplayFeed(req.es_csv, req.nq_csv)
            bt = Backtester(feed, traded=Symbol(req.traded), slippage_points=req.slippage)
            return bt.run()

        res = await anyio.to_thread.run_sync(_run)
        async with st.db.session() as s:
            repo = Repository(s)
            await repo.add_setups(res.setups, TradeMode.BACKTEST)
            await repo.add_trades(res.trades)
        return {"n_setups": len(res.setups), "n_signals": res.n_signals,
                "n_trades": res.n_trades, "summary": summarize(res.trades)}

    @app.post("/api/control/kill")
    async def kill(reason: str = "manual", authorization: str | None = Header(default=None),
                   st: AppState = Depends(get_state)) -> dict:
        _require_control(st, authorization)
        st.kill.activate(reason)
        return {"active": st.kill.active, "reason": st.kill.reason}

    @app.post("/api/control/resume")
    async def resume(authorization: str | None = Header(default=None),
                     st: AppState = Depends(get_state)) -> dict:
        _require_control(st, authorization)
        st.kill.deactivate()
        return {"active": st.kill.active}

    @app.post("/api/trades")
    async def log_trade(req: LogTradeRequest, authorization: str | None = Header(default=None),
                        st: AppState = Depends(get_state)) -> dict:
        """Journal a manual trade so it feeds the per-condition analytics (auth-gated)."""
        _require_control(st, authorization)
        trade = _make_trade(
            side=req.side, realized_r=req.realized_r, mode=req.mode,
            killzone=req.killzone, quarter_idx=req.quarter_idx, day_of_week=req.day_of_week,
            path_clean=req.path_clean, moved_to_be_early=req.moved_to_be_early,
            exit_reason=req.exit_reason, entry_px=req.entry_px, exit_px=req.exit_px,
            realized_pnl=req.realized_pnl,
        )
        async with st.db.session() as s:
            await Repository(s).add_trade(trade)
        return {"ok": True, "mode": trade.mode.value, "realized_r": trade.realized_r}

    @app.post("/api/broker/test")
    async def broker_test(authorization: str | None = Header(default=None),
                          st: AppState = Depends(get_state)) -> dict:
        """Authenticate against Tradovate (demo unless mode=live) and confirm the account.

        Reads TRADOVATE_* creds from the environment; never returns the secrets.
        """
        _require_control(st, authorization)
        import httpx

        from ..config import get_tradovate_settings
        from ..execution.tradovate_rest import TradovateCredentials, TradovateREST

        ts = get_tradovate_settings()
        if not ts.configured:
            return {"connected": False, "mode": st.settings.mode.value,
                    "error": "Tradovate credentials not set — fill TRADOVATE_* in .env"}
        creds = TradovateCredentials(
            name=ts.name, password=ts.password, app_id=ts.app_id,
            app_version=ts.app_version, cid=ts.cid, sec=ts.secret, device_id=ts.device_id)
        client = httpx.AsyncClient(timeout=8.0)
        rest = TradovateREST(st.settings.tradovate_base_url, creds, client=client)
        try:
            result = await rest.verify()
        finally:
            await client.aclose()
        result["mode"] = st.settings.mode.value
        return result

    @app.post("/webhooks/pine")
    async def pine_webhook(alert: PineAlert, st: AppState = Depends(get_state)) -> dict:
        secret = st.settings.webhook_secret
        if secret and not hmac.compare_digest(alert.secret or "", secret):
            raise HTTPException(status_code=403, detail="bad webhook secret")
        payload = alert.model_dump(exclude={"secret"})
        trade_logged = False
        async with st.db.session() as s:
            repo = Repository(s)
            await repo.log_webhook(datetime.now(UTC), payload)
            # A TradingView *strategy* posts kind="trade" on each closed round-trip, so the
            # per-condition analytics accrue with NO broker API. Webhook trades are ALWAYS
            # demo — a public webhook URL must never be able to write live-mode data.
            if alert.kind == "trade" and alert.realized_r is not None:
                trade = _make_trade(
                    side=alert.side or alert.bias or "long",
                    realized_r=alert.realized_r, mode="demo",
                    killzone=alert.killzone or "ny_am",
                    quarter_idx=alert.quarter if alert.quarter is not None else -1,
                    day_of_week=alert.day_of_week, path_clean=alert.path_clean,
                    moved_to_be_early=alert.moved_to_be_early,
                    exit_reason=alert.exit_reason or "tp",
                    entry_px=alert.entry or 0.0, exit_px=alert.exit,
                )
                await repo.add_trade(trade)
                trade_logged = True
        await st.hub.broadcast({"type": "pine_alert", "alert": payload})
        return {"ok": True, "trade_logged": trade_logged}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await st_ws(state, ws)

    # Serve the built research-deck SPA from FastAPI (one process, one port) when a build
    # exists. API routes above are registered first, so they take precedence over this
    # catch-all mount. Headless (no build) is fine — the JSON API still works.
    static_dir = os.environ.get("ICT_TRADER_STATIC_DIR", "frontend/dist")
    if os.path.isdir(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="deck")

    return app


async def st_ws(state: AppState, ws: WebSocket) -> None:
    await state.hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except Exception:  # noqa: BLE001
        await state.hub.disconnect(ws)
