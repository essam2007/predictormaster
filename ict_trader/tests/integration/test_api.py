from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="requires the [serve] extra")

from fastapi.testclient import TestClient  # noqa: E402

from ict_trader.api.app import create_app  # noqa: E402
from ict_trader.config import Settings  # noqa: E402


def _write_csv(path: Path, jitter: float) -> None:
    start = datetime(2024, 5, 15, 7, 0)  # naive -> treated as ET by the replay reader
    lines = ["timestamp,open,high,low,close,volume"]
    for i in range(240):
        ts = start + timedelta(minutes=i)
        base = (100.0 - i * 0.05) if i < 170 else (100.0 - 170 * 0.05 + (i - 170) * 0.12)
        o = base + jitter
        c = base + jitter + (0.03 if i >= 170 else -0.03)
        h = max(o, c) + 0.05
        low = min(o, c) - 0.05
        lines.append(f"{ts.isoformat()},{o:.4f},{h:.4f},{low:.4f},{c:.4f},10")
    path.write_text("\n".join(lines))


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "test.db"
    settings = Settings(db_url=f"sqlite+aiosqlite:///{db}", control_token="secret")
    app = create_app(settings)
    with TestClient(app) as c:
        yield c, tmp_path


def test_healthz_and_status(client):
    c, _ = client
    assert c.get("/healthz").json()["ok"] is True
    status = c.get("/api/status").json()
    assert status["mode"] == "demo"
    assert status["kill_switch"]["active"] is False


def test_backtest_then_analytics(client):
    c, tmp = client
    es, nq = tmp / "es.csv", tmp / "nq.csv"
    _write_csv(es, jitter=-0.01)
    _write_csv(nq, jitter=0.0)
    r = c.post("/api/backtest", json={"es_csv": str(es), "nq_csv": str(nq), "traded": "NQ"})
    assert r.status_code == 200
    body = r.json()
    assert body["n_setups"] > 0
    summary = c.get("/api/analytics/summary?mode=backtest").json()
    assert "overall" in summary and "buckets" in summary


def test_kill_switch_requires_auth(client):
    c, _ = client
    assert c.post("/api/control/kill").status_code == 401
    ok = c.post("/api/control/kill", headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200 and ok.json()["active"] is True
    resumed = c.post("/api/control/resume", headers={"Authorization": "Bearer secret"})
    assert resumed.json()["active"] is False


def test_pine_webhook(client):
    c, _ = client
    r = c.post("/webhooks/pine", json={"source": "pine", "symbol": "NQ", "bias": "long"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_log_trade_feeds_demo_analytics(client):
    c, _ = client
    # unauth -> 401
    assert c.post("/api/trades", json={"side": "long", "realized_r": 1.0}).status_code == 401
    # log two demo trades: one clean winner, one early-breakeven loser
    h = {"Authorization": "Bearer secret"}
    assert c.post("/api/trades", headers=h, json={
        "side": "long", "realized_r": 2.5, "killzone": "silver_bullet",
        "path_clean": True, "moved_to_be_early": False, "exit_reason": "runner_target"}).status_code == 200
    assert c.post("/api/trades", headers=h, json={
        "side": "short", "realized_r": -1.0, "moved_to_be_early": True,
        "exit_reason": "be"}).status_code == 200
    # they show up under demo analytics, split by the breakeven bucket
    summary = c.get("/api/analytics/summary?mode=demo").json()
    assert summary["overall"]["n"] == 2
    be = {b["label"]: b for b in summary["buckets"]["moved_to_be_early"]}
    assert "be_early" in be and "no_be_early" in be


def test_broker_test_requires_auth_and_reports_unconfigured(client, monkeypatch):
    c, _ = client
    # no auth -> 401
    assert c.post("/api/broker/test").status_code == 401
    # with auth but no creds set -> clear "not configured" (no network call)
    from ict_trader import config
    config.get_tradovate_settings.cache_clear()
    for var in ("TRADOVATE_NAME", "TRADOVATE_PASSWORD", "TRADOVATE_CID", "TRADOVATE_SECRET"):
        monkeypatch.delenv(var, raising=False)
    r = c.post("/api/broker/test", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert "credentials not set" in body["error"]
