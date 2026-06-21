"""FastAPI research-deck backend.

Read-mostly views over the store (per-bucket analytics, trade journal, equity) plus a
guarded control surface (kill switch) and the Pine webhook receiver. The frontend renders
these; nothing here can place an order (the live engine owns execution).
"""

from __future__ import annotations

import asyncio
import csv
import hmac
import io
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..analytics.calibration import component_lift, score_reliability
from ..analytics.metrics import equity_curve, summarize
from ..analytics.trade_analyzer import analyze_trade
from ..config import Settings, get_settings
from ..domain.bars import Bar
from ..domain.enums import (
    AMDPhase,
    BreakevenTrigger,
    ExitReason,
    Killzone,
    Side,
    Symbol,
    Timeframe,
    TradeMode,
)
from ..domain.trades import Trade
from ..execution.kill_switch import KillSwitch
from ..execution.risk import RiskEngine
from ..llm.grader import grade_available, grade_trade
from ..store.db import Database
from ..store.repositories import Repository, bar_epoch
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


def _normalize_bars(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept the compact keys a Pine alert sends (t/o/h/l/c/v) or full names, and convert
    the timestamp (unix seconds or ISO string) to a tz-aware datetime."""
    def pick(b: dict[str, Any], *keys: str) -> Any:
        for k in keys:
            if b.get(k) is not None:
                return b[k]
        return None

    out: list[dict[str, Any]] = []
    for b in raw:
        t = pick(b, "t", "time", "ts")
        o, h, low, c = pick(b, "o", "open"), pick(b, "h", "high"), pick(b, "l", "low"), pick(b, "c", "close")
        if t is None or None in (o, h, low, c):
            continue  # skip a malformed bar rather than rejecting the whole alert
        if isinstance(t, int | float):
            ts = datetime.fromtimestamp(float(t), tz=UTC)
        else:
            ts = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
        try:
            out.append({
                "ts": ts, "open": float(o), "high": float(h), "low": float(low),
                "close": float(c), "volume": float(pick(b, "v", "volume") or 0.0),
            })
        except (TypeError, ValueError):
            continue
    return out


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
    entry_ts: datetime | None = None,
) -> Trade:
    """Build a realized Trade from journaled/webhook/click fields (shared by all sources)."""
    ts = entry_ts or datetime.now(UTC)
    dow = day_of_week if day_of_week >= 0 else ts.weekday()
    be = (
        BreakevenTrigger.EARLY_PULLBACK
        if moved_to_be_early
        else BreakevenTrigger.STRUCTURAL_BREAK
    )
    return Trade(
        symbol=Symbol.NQ,
        side=_enum(Side, side, Side.LONG),
        entry_ts=ts,
        entry_px=entry_px,
        qty_initial=1,
        mode=_enum(TradeMode, mode, TradeMode.DEMO),
        exit_ts=ts,
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


def _parse_ts(value: str) -> datetime:
    """Parse a chart timestamp (unix seconds or ISO string) to a tz-aware UTC datetime."""
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError):
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _rows_to_bars(rows: list, symbol: str) -> list[Bar]:
    """Build domain Bars from stored BarRows so the detectors can run over the window."""
    sym = _enum(Symbol, symbol, Symbol.NQ)
    out: list[Bar] = []
    for r in rows:
        ts = r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=UTC)
        out.append(Bar(symbol=sym, timeframe=Timeframe.M5, ts_open=ts, open=r.open,
                       high=r.high, low=r.low, close=r.close, volume=r.volume))
    return out


async def _analyze_and_store(
    repo: Repository, trade_id: int, *, side: str, entry_ts: datetime, mode: str,
    killzone: str, path_clean: bool, moved_to_be_early: bool, realized_r: float = 0.0,
    symbol: str = "NQ",
) -> None:
    """Run the detector suite over the trade's bar window and persist the grade.

    Best-effort: any failure (e.g. no bars yet) is swallowed so logging a trade never breaks.
    """
    try:
        rows = await repo.list_bars(mode, symbol, "5", 500)
        bars = _rows_to_bars(rows, symbol)
        analysis = analyze_trade(
            side=side, entry_ts=entry_ts, bars=bars, killzone=killzone,
            path_clean=path_clean, moved_to_be_early=moved_to_be_early,
        )
        # Optional Claude narrative grade (Phase E) — no-ops instantly without ANTHROPIC_API_KEY;
        # when configured, run off-thread so the network call doesn't block the event loop.
        llm_grade = llm_rationale = None
        if grade_available():
            import anyio
            llm = await anyio.to_thread.run_sync(
                lambda: grade_trade(
                    side=side, realized_r=realized_r, elements=analysis.to_dict()["elements"],
                    summary=analysis.summary, killzone=killzone,
                    moved_to_be_early=moved_to_be_early))
            if llm is not None:
                llm_grade, llm_rationale = llm.grade, f"[{llm.model}] {llm.rationale}"
        await repo.save_trade_analysis(
            trade_id, mode, analysis.to_dict(), llm_grade=llm_grade, llm_rationale=llm_rationale)
    except Exception:  # noqa: BLE001 - analysis is advisory, never fatal to logging
        pass


# Flattened training-dataset schema: per-trade features (tags + detected elements) + outcome.
_ELEMENT_COLS = {
    "HTF FVG delivery": "el_htf_fvg",
    "IFVG / LTF trigger": "el_ifvg",
    "Structure shift (BOS)": "el_bos",
    "Displacement leg": "el_displacement",
    "Killzone timing": "el_killzone",
    "Clean path (LRLR)": "el_clean_path",
}
DATASET_COLUMNS = [
    "trade_id", "entry_ts", "side", "killzone", "quarter_idx", "day_of_week",
    "path_clean", "moved_to_be_early", "exit_reason", "setup_score",
    "analysis_score", "analysis_grade",
    *_ELEMENT_COLS.values(),
    "realized_r", "realized_pnl", "win",
]


def _dataset_rows(rows: list, analyses: dict) -> list[dict[str, Any]]:
    """Flatten trades + their analysis into one labeled feature row each (for model training)."""
    out: list[dict[str, Any]] = []
    for r in rows:
        a = analyses.get(r.id)
        rec: dict[str, Any] = {
            "trade_id": r.id, "entry_ts": r.entry_ts.isoformat(), "side": r.side,
            "killzone": r.killzone, "quarter_idx": r.quarter_idx, "day_of_week": r.day_of_week,
            "path_clean": int(r.path_clean), "moved_to_be_early": int(r.moved_to_be_early),
            "exit_reason": r.exit_reason, "setup_score": r.setup_score,
            "analysis_score": a.score if a else None,
            "analysis_grade": a.grade if a else None,
            "realized_r": r.realized_r, "realized_pnl": r.realized_pnl,
            "win": int(r.realized_r > 0),
        }
        present = {e["name"]: e["present"] for e in (a.elements if a else [])}
        for name, col in _ELEMENT_COLS.items():
            rec[col] = int(present[name]) if name in present else None
        out.append(rec)
    return out


class BacktestRequest(BaseModel):
    es_csv: str
    nq_csv: str
    traded: str = "NQ"
    slippage: float = 0.25


class LoginRequest(BaseModel):
    """Dashboard login (single-user cockpit). The password is the user's own self-set
    value (ICT_TRADER_DASHBOARD_PASSWORD), falling back to the control token."""

    user: str = ""
    password: str = ""


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


class LogEntryRequest(BaseModel):
    """A trade marked by clicking the chart — the entry time/price come from the click, so the
    detector window is the real pre-entry window. Always logged demo."""

    entry_ts: str  # unix-seconds or ISO string captured from the chart click
    entry_px: float = 0.0
    side: str = "long"
    realized_r: float = 0.0
    exit_px: float | None = None
    killzone: str = "ny_am"
    quarter_idx: int = -1
    path_clean: bool = True
    moved_to_be_early: bool = False
    exit_reason: str = "manual"
    note: str = ""
    symbol: str = "NQ"


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
    # chart-data fields: a Pine bar-feed alert carries the latest closed OHLC bar(s) so the
    # deck can draw real candles + run detectors over a trade's window (no broker API).
    timeframe: str | None = None
    bars: list[dict[str, Any]] = []


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

    def require_view(authorization: str | None = Header(default=None)) -> None:
        """Gate the read API when login is required (makes the public URL private).

        A no-op unless ICT_TRADER_REQUIRE_LOGIN is set; then a valid Bearer token (the
        one /api/login hands back, == the control token) is required to read anything.
        """
        if not settings.require_login:
            return
        token = (authorization or "").removeprefix("Bearer ").strip()
        expected = settings.control_token
        if not expected or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="login required")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "mode": settings.mode.value}

    @app.get("/api/auth/config")
    async def auth_config() -> dict:
        """Public: lets the SPA know whether to show a login screen first."""
        return {"login_required": settings.require_login, "user": settings.dashboard_user}

    @app.post("/api/login")
    async def login(req: LoginRequest) -> dict:
        """Validate the user's own credentials and hand back the control token.

        The token then authorizes both reads (when login is required) and control
        actions, so the user never has to paste a token by hand.
        """
        expected_pw = settings.login_password
        if not expected_pw:
            raise HTTPException(
                status_code=503,
                detail="no dashboard password configured (set ICT_TRADER_DASHBOARD_PASSWORD "
                "or ICT_TRADER_CONTROL_TOKEN)",
            )
        user_ok = hmac.compare_digest(req.user or "", settings.dashboard_user)
        pw_ok = hmac.compare_digest(req.password or "", expected_pw)
        if not (user_ok and pw_ok):
            raise HTTPException(status_code=401, detail="invalid credentials")
        return {"ok": True, "token": settings.control_token, "user": settings.dashboard_user}

    @app.get("/api/status")
    async def status(st: AppState = Depends(get_state),
                     _: None = Depends(require_view)) -> dict:
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
    async def analytics_summary(mode: str = "backtest", st: AppState = Depends(get_state),
                                _: None = Depends(require_view)) -> dict:
        async with st.db.session() as s:
            trades = await Repository(s).list_trades(TradeMode(mode))
        return summarize(trades)

    @app.get("/api/analytics/equity")
    async def analytics_equity(mode: str = "backtest", st: AppState = Depends(get_state),
                               _: None = Depends(require_view)) -> list:
        async with st.db.session() as s:
            trades = await Repository(s).list_trades(TradeMode(mode))
        return equity_curve(trades)

    @app.get("/api/analytics/calibration")
    async def analytics_calibration(mode: str = "backtest",
                                    st: AppState = Depends(get_state),
                                    _: None = Depends(require_view)) -> dict:
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
                          st: AppState = Depends(get_state),
                          _: None = Depends(require_view)) -> list:
        async with st.db.session() as s:
            repo = Repository(s)
            rows = await repo.list_trade_rows(TradeMode(mode))
            analyses = await repo.analyses_by_trade(TradeMode(mode))
        out = []
        for r in rows[:limit]:
            a = analyses.get(r.id)
            out.append({
                "id": r.id,
                "entry_ts": r.entry_ts.isoformat(), "side": r.side,
                "entry_px": r.entry_px, "exit_px": r.exit_px,
                "realized_r": r.realized_r, "realized_pnl": r.realized_pnl,
                "killzone": r.killzone, "quarter_idx": r.quarter_idx,
                "day_of_week": r.day_of_week, "path_clean": r.path_clean,
                "moved_to_be_early": r.moved_to_be_early, "exit_reason": r.exit_reason,
                "analysis_score": a.score if a else None,
                "analysis_grade": a.grade if a else None,
            })
        return out

    @app.get("/api/trades/{trade_id}/analysis")
    async def trade_analysis(trade_id: int, st: AppState = Depends(get_state),
                             _: None = Depends(require_view)) -> dict:
        """The auto-detected setup elements + grade for one trade (the AI-detector output)."""
        async with st.db.session() as s:
            a = await Repository(s).get_trade_analysis(trade_id)
        if a is None:
            raise HTTPException(status_code=404, detail="no analysis for this trade")
        return {"trade_id": a.trade_id, "score": a.score, "grade": a.grade,
                "summary": a.summary, "elements": a.elements, "model": a.model,
                "llm_grade": a.llm_grade, "llm_rationale": a.llm_rationale}

    @app.get("/api/dataset")
    async def dataset(mode: str = "demo", st: AppState = Depends(get_state),
                      _: None = Depends(require_view)) -> dict:
        """Preview the training dataset: every trade flattened to a labeled feature row."""
        async with st.db.session() as s:
            repo = Repository(s)
            rows = await repo.list_trade_rows(TradeMode(mode))
            analyses = await repo.analyses_by_trade(TradeMode(mode))
        recs = _dataset_rows(rows, analyses)
        return {"n": len(recs), "columns": DATASET_COLUMNS, "rows": recs[:100]}

    @app.get("/api/dataset/export")
    async def dataset_export(mode: str = "demo", format: str = "jsonl",
                             st: AppState = Depends(get_state),
                             _: None = Depends(require_view)) -> Response:
        """Download the full labeled dataset for model training (jsonl or csv)."""
        async with st.db.session() as s:
            repo = Repository(s)
            rows = await repo.list_trade_rows(TradeMode(mode))
            analyses = await repo.analyses_by_trade(TradeMode(mode))
        recs = _dataset_rows(rows, analyses)
        if format == "csv":
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=DATASET_COLUMNS)
            writer.writeheader()
            writer.writerows(recs)
            content, media, ext = buf.getvalue(), "text/csv", "csv"
        else:
            content = "\n".join(json.dumps(rec) for rec in recs)
            media, ext = "application/x-ndjson", "jsonl"
        return Response(content=content, media_type=media, headers={
            "Content-Disposition": f"attachment; filename=ict_trades_{mode}.{ext}"})

    @app.get("/api/webhooks")
    async def list_webhooks(limit: int = 100, st: AppState = Depends(get_state),
                            _: None = Depends(require_view)) -> list:
        """Recent TradingView alerts that landed on /webhooks/pine (signals + trades)."""
        async with st.db.session() as s:
            rows = await Repository(s).list_webhooks(limit)
        return [{"ts": r.ts.isoformat(), "matched": r.matched, **r.payload} for r in rows]

    @app.get("/api/bars")
    async def list_bars(symbol: str = "NQ", timeframe: str = "5", mode: str = "demo",
                        limit: int = 500, st: AppState = Depends(get_state),
                        _: None = Depends(require_view)) -> list:
        """OHLC bars for charting (Lightweight Charts format: unix-second `time`)."""
        async with st.db.session() as s:
            rows = await Repository(s).list_bars(mode, symbol, timeframe, limit)
        return [
            {"time": bar_epoch(r.ts), "open": r.open, "high": r.high,
             "low": r.low, "close": r.close, "volume": r.volume}
            for r in rows
        ]

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
            repo = Repository(s)
            tid = await repo.add_trade(trade)
            await _analyze_and_store(
                repo, tid, side=trade.side.value, entry_ts=trade.entry_ts,
                mode=trade.mode.value, killzone=trade.killzone.value,
                path_clean=trade.path_clean, moved_to_be_early=trade.moved_to_be_early,
                realized_r=trade.realized_r, symbol=trade.symbol.value)
        return {"ok": True, "mode": trade.mode.value, "realized_r": trade.realized_r}

    @app.post("/api/log-entry")
    async def log_entry(req: LogEntryRequest, authorization: str | None = Header(default=None),
                        st: AppState = Depends(get_state)) -> dict:
        """Click-to-log: turn a chart point into a graded demo trade fed into the dataset.

        The entry timestamp comes from the click, so the detector window is the actual
        pre-entry window. Always demo (the chart tool never writes live data)."""
        _require_control(st, authorization)
        ets = _parse_ts(req.entry_ts)
        trade = _make_trade(
            side=req.side, realized_r=req.realized_r, mode="demo", killzone=req.killzone,
            quarter_idx=req.quarter_idx, day_of_week=-1, path_clean=req.path_clean,
            moved_to_be_early=req.moved_to_be_early, exit_reason=req.exit_reason,
            entry_px=req.entry_px, exit_px=req.exit_px, entry_ts=ets,
        )
        async with st.db.session() as s:
            repo = Repository(s)
            tid = await repo.add_trade(trade)
            await _analyze_and_store(
                repo, tid, side=trade.side.value, entry_ts=trade.entry_ts, mode="demo",
                killzone=trade.killzone.value, path_clean=trade.path_clean,
                moved_to_be_early=trade.moved_to_be_early, realized_r=trade.realized_r,
                symbol=req.symbol)
        return {"ok": True, "trade_id": tid, "entry_ts": trade.entry_ts.isoformat()}

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
        bars_added = 0
        async with st.db.session() as s:
            repo = Repository(s)
            await repo.log_webhook(datetime.now(UTC), payload)
            # Bars are ALWAYS stored under demo (a public webhook must never write live data).
            if alert.bars:
                bars_added = await repo.add_bars(
                    "demo", alert.symbol or "NQ", alert.timeframe or "5",
                    _normalize_bars(alert.bars),
                )
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
                tid = await repo.add_trade(trade)
                await _analyze_and_store(
                    repo, tid, side=trade.side.value, entry_ts=trade.entry_ts, mode="demo",
                    killzone=trade.killzone.value, path_clean=trade.path_clean,
                    moved_to_be_early=trade.moved_to_be_early, realized_r=trade.realized_r,
                    symbol=trade.symbol.value)
                trade_logged = True
        await st.hub.broadcast({"type": "pine_alert", "alert": payload})
        return {"ok": True, "trade_logged": trade_logged, "bars_added": bars_added}

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
