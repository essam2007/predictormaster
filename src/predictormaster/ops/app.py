"""FastAPI app for the operations dashboard.

Endpoints
---------
GET  /                            → serves index.html
GET  /api/status                  → runner state + kill switch
GET  /api/balance                 → proxy USDC + EOA MATIC
GET  /api/metrics                 → PnL / Sharpe / win-rate from journal
GET  /api/decisions?limit=N       → recent journal rows (newest first)
GET  /api/runner-stdout?n=N       → tail of runner stdout log
POST /api/start                   → spawn live_runner subprocess
POST /api/stop                    → SIGTERM the running subprocess
POST /api/kill-switch/trip        → trip the kill switch (file-based)
POST /api/kill-switch/reset       → clear the kill switch file

Bind to 127.0.0.1 only. No auth — relies on loopback isolation.

Live-mode safety
----------------
POST /api/start with mode="live" requires
    confirmation = "I UNDERSTAND THIS IS REAL MONEY"
in the body. The frontend forces a typed modal before submitting.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..execution.kill_switch import KillSwitch
from .balance import fetch_balances
from .diagnose import diagnose, sample_polymarket_edges
from .metrics import compute_metrics, load_decisions, recent_decisions
from .runner import LIVE_CONFIRMATION_TOKEN, RunnerManager, SnapshotLoggerManager

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATIC_DIR = Path(__file__).resolve().parent / "static"
JOURNAL_PATH = PROJECT_ROOT / "logs" / "decisions.jsonl"
KILL_FILE = Path.home() / ".predictormaster.kill"


class StartRequest(BaseModel):
    mode: str = Field(..., pattern="^(shadow|paper|live)$")
    bankroll: float = Field(15.0, gt=0)
    max_stake: float = Field(2.0, gt=0)
    min_edge: float = Field(0.005, ge=0, le=1)
    interval: float = Field(60.0, ge=5)
    confirmation: str | None = None


class TripRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)


class LoggerStartRequest(BaseModel):
    snapshot_interval: float = Field(5.0, ge=1.0, le=60.0)
    discovery_interval: float = Field(900.0, ge=60.0, le=3600.0)
    market_limit: int = Field(80, ge=1, le=500)


def _load_dotenv_into_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
        logger.info("loaded .env from %s", env_path)
    except ImportError:
        logger.warning("python-dotenv not installed; skipping .env load")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_dotenv_into_env()
    app.state.runner = RunnerManager(project_root=PROJECT_ROOT)
    app.state.logger = SnapshotLoggerManager(project_root=PROJECT_ROOT)
    app.state.kill_switch = KillSwitch(kill_file=KILL_FILE)
    # Diagnostic edge-sample cache (sampling takes ~30s; the dashboard
    # polls cheaply and only triggers a fresh sample if cache is stale)
    app.state.edge_sample_cache = {"value": None, "expires_at": 0.0}
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="predictormaster ops", lifespan=lifespan)

    @app.get("/api/status")
    def status() -> dict:
        runner = app.state.runner.status()
        ks = app.state.kill_switch.status()
        return {
            "runner": runner,
            "kill_switch": ks,
            "live_confirmation_token": LIVE_CONFIRMATION_TOKEN,
            "project_root": str(PROJECT_ROOT),
            "credentials_present": all(os.environ.get(k) for k in (
                "POLY_API_KEY", "POLY_API_SECRET", "POLY_API_PASSPHRASE",
                "POLY_PROXY_ADDRESS", "POLY_FUNDER_PK",
            )),
        }

    @app.get("/api/balance")
    def balance() -> dict:
        return fetch_balances().to_dict()

    @app.get("/api/metrics")
    def metrics() -> dict:
        rows = load_decisions(JOURNAL_PATH)
        return compute_metrics(rows)

    @app.get("/api/decisions")
    def decisions(limit: int = Query(50, ge=1, le=500)) -> dict:
        rows = load_decisions(JOURNAL_PATH)
        return {"rows": recent_decisions(rows, limit=limit),
                "total": len(rows)}

    @app.get("/api/runner-stdout")
    def runner_stdout(n: int = Query(80, ge=1, le=1000)) -> dict:
        return {"lines": app.state.runner.recent_stdout(n_lines=n)}

    @app.post("/api/start")
    def start(req: StartRequest) -> dict:
        try:
            return app.state.runner.start(
                mode=req.mode, bankroll=req.bankroll,
                max_stake=req.max_stake, min_edge=req.min_edge,
                interval=req.interval, confirmation=req.confirmation,
            )
        except PermissionError as e:
            raise HTTPException(403, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(409, detail=str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(500, detail=str(e)) from e

    @app.post("/api/stop")
    def stop() -> dict:
        return app.state.runner.stop()

    @app.post("/api/kill-switch/trip")
    def kill_trip(req: TripRequest) -> dict:
        app.state.kill_switch.trip(req.reason)
        # Persist via the file mechanism so it survives a server restart.
        try:
            KILL_FILE.write_text(f"tripped via ops dashboard: {req.reason}\n")
        except OSError as e:
            raise HTTPException(500, detail=f"could not write kill file: {e}") from e
        return app.state.kill_switch.status()

    @app.post("/api/kill-switch/reset")
    def kill_reset() -> dict:
        app.state.kill_switch.reset()
        try:
            if KILL_FILE.exists():
                KILL_FILE.unlink()
        except OSError as e:
            raise HTTPException(500, detail=f"could not remove kill file: {e}") from e
        return app.state.kill_switch.status()

    # ---------------- snapshot logger sidecar ----------------

    @app.get("/api/logger/status")
    def logger_status() -> dict:
        return app.state.logger.status()

    @app.get("/api/logger/stdout")
    def logger_stdout(n: int = Query(60, ge=1, le=500)) -> dict:
        return {"lines": app.state.logger.recent_stdout(n_lines=n)}

    @app.post("/api/logger/start")
    def logger_start(req: LoggerStartRequest) -> dict:
        try:
            return app.state.logger.start(
                snapshot_interval=req.snapshot_interval,
                discovery_interval=req.discovery_interval,
                market_limit=req.market_limit,
            )
        except ValueError as e:
            raise HTTPException(400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(409, detail=str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(500, detail=str(e)) from e

    @app.post("/api/logger/stop")
    def logger_stop() -> dict:
        return app.state.logger.stop()

    # ---------------- diagnostics ----------------

    @app.get("/api/diagnostics")
    def diagnostics(refresh_sample: bool = Query(False)) -> dict:
        """Why aren't orders filling? Returns a verdict + actionable
        suggestions. The expensive part — sampling live PM edges —
        is cached for 5 minutes (or refreshed on demand)."""
        import time as _time
        cache = app.state.edge_sample_cache
        if refresh_sample or cache["value"] is None or _time.time() > cache["expires_at"]:
            sample = sample_polymarket_edges(limit=80, timeout_seconds=70.0)
            cache["value"] = sample
            cache["expires_at"] = _time.time() + 300.0
        report = diagnose(
            journal_path=JOURNAL_PATH,
            edge_sample=cache["value"],
        )
        return report.to_dict()

    # ---- static frontend ----
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        idx = STATIC_DIR / "index.html"
        if not idx.exists():
            return JSONResponse({"error": "index.html missing"}, status_code=500)
        return FileResponse(idx)

    return app
