from __future__ import annotations

import json
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
    # backtest is auth-gated (it reads server-side paths) — unauthenticated is rejected
    assert c.post("/api/backtest", json={"es_csv": str(es), "nq_csv": str(nq)}).status_code == 401
    r = c.post("/api/backtest", headers={"Authorization": "Bearer secret"},
               json={"es_csv": str(es), "nq_csv": str(nq), "traded": "NQ"})
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
    # a plain signal alert is logged but creates no trade
    assert r.json()["trade_logged"] is False


def test_pine_webhook_trade_feeds_demo_analytics(client):
    """A TradingView strategy fires kind='trade' webhooks -> demo trades, no broker API."""
    c, _ = client
    win = c.post("/webhooks/pine", json={
        "source": "pine", "kind": "trade", "symbol": "NQ", "side": "long",
        "realized_r": 2.0, "killzone": "silver_bullet", "moved_to_be_early": False,
        "exit_reason": "runner_target", "quarter": 1, "day_of_week": 2})
    assert win.status_code == 200 and win.json()["trade_logged"] is True
    loss = c.post("/webhooks/pine", json={
        "source": "pine", "kind": "trade", "side": "short",
        "realized_r": -1.0, "moved_to_be_early": True, "exit_reason": "be"})
    assert loss.json()["trade_logged"] is True
    # webhook trades land under DEMO and split by the breakeven bucket
    summary = c.get("/api/analytics/summary?mode=demo").json()
    assert summary["overall"]["n"] == 2
    be = {b["label"]: b for b in summary["buckets"]["moved_to_be_early"]}
    assert "be_early" in be and "no_be_early" in be


def test_webhooks_feed_lists_recent_alerts(client):
    c, _ = client
    c.post("/webhooks/pine", json={"source": "pine", "symbol": "NQ", "bias": "long"})
    c.post("/webhooks/pine", json={"source": "pine", "kind": "trade", "side": "short",
                                   "realized_r": 1.5, "exit_reason": "runner_target"})
    feed = c.get("/api/webhooks").json()
    assert len(feed) == 2
    # newest first; trade-kind alert carries its realized_r through the feed
    assert feed[0]["kind"] == "trade" and feed[0]["realized_r"] == 1.5


def test_pine_webhook_ingests_bars_for_charting(client):
    """A Pine bar-feed alert carries OHLC bars -> stored under demo and served for charts."""
    c, _ = client
    bars = [
        {"t": 1715780100, "o": 18000, "h": 18010, "l": 17995, "c": 18008, "v": 900},
        {"t": 1715780400, "o": 18008, "h": 18020, "l": 18004, "c": 18016, "v": 1100},
    ]
    r = c.post("/webhooks/pine", json={"source": "pine", "symbol": "NQ",
                                       "timeframe": "5", "bars": bars})
    assert r.status_code == 200 and r.json()["bars_added"] == 2
    # re-sending the same bars is idempotent (natural-key dedup)
    assert c.post("/webhooks/pine", json={"source": "pine", "symbol": "NQ",
                                          "timeframe": "5", "bars": bars}).json()["bars_added"] == 0
    feed = c.get("/api/bars?symbol=NQ&timeframe=5&mode=demo").json()
    assert len(feed) == 2
    # chronological, Lightweight-Charts shape (unix-second `time`)
    assert feed[0]["time"] == 1715780100 and feed[0]["close"] == 18008
    assert feed[1]["time"] == 1715780400 and feed[1]["high"] == 18020


def test_pine_webhook_trade_never_writes_live(client):
    """Even if a payload claims mode=live, webhook trades are forced to demo."""
    c, _ = client
    c.post("/webhooks/pine", json={
        "source": "pine", "kind": "trade", "side": "long", "realized_r": 1.0,
        "mode": "live"})  # 'mode' is ignored by the webhook on purpose
    assert c.get("/api/analytics/summary?mode=live").json()["overall"]["n"] == 0
    assert c.get("/api/analytics/summary?mode=demo").json()["overall"]["n"] == 1


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


def test_auth_config_public_and_open_by_default(client):
    """With login not required, /api/auth/config says so and reads are open."""
    c, _ = client
    cfg = c.get("/api/auth/config").json()
    assert cfg["login_required"] is False
    # reads work without any token when login isn't required
    assert c.get("/api/status").status_code == 200


def test_login_returns_control_token(client):
    """Login validates the dashboard creds and hands back the control token."""
    c, _ = client
    # default dashboard_user is "admin"; password falls back to the control token
    bad = c.post("/api/login", json={"user": "admin", "password": "wrong"})
    assert bad.status_code == 401
    ok = c.post("/api/login", json={"user": "admin", "password": "secret"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True and body["token"] == "secret" and body["user"] == "admin"


@pytest.fixture
def locked_client(tmp_path):
    """A deck that requires login (the hosted-cockpit config)."""
    db = tmp_path / "locked.db"
    settings = Settings(
        db_url=f"sqlite+aiosqlite:///{db}", control_token="tok",
        require_login=True, dashboard_user="trader", dashboard_password="s3cret",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_require_login_gates_reads(locked_client):
    c = locked_client
    # config advertises the gate; healthz + login stay public
    cfg = c.get("/api/auth/config").json()
    assert cfg["login_required"] is True and cfg["user"] == "trader"
    assert c.get("/healthz").status_code == 200
    # reads are blocked without a token
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/analytics/summary?mode=demo").status_code == 401
    # wrong creds rejected
    assert c.post("/api/login", json={"user": "trader", "password": "nope"}).status_code == 401
    # correct creds -> token; authed reads pass
    token = c.post("/api/login", json={"user": "trader", "password": "s3cret"}).json()["token"]
    assert token == "tok"
    h = {"Authorization": f"Bearer {token}"}
    assert c.get("/api/status", headers=h).status_code == 200
    assert c.get("/api/analytics/summary?mode=demo", headers=h).status_code == 200
    # the webhook stays public (TradingView can't send a bearer token)
    assert c.post("/webhooks/pine", json={"source": "pine", "bias": "long"}).status_code == 200


def test_login_503_when_no_password_configured(tmp_path):
    db = tmp_path / "nopw.db"
    settings = Settings(db_url=f"sqlite+aiosqlite:///{db}")  # no control token, no password
    app = create_app(settings)
    with TestClient(app) as c:
        assert c.post("/api/login", json={"user": "admin", "password": "x"}).status_code == 503


def test_logged_trade_gets_auto_analysis(client):
    """Logging a trade auto-runs the detector suite over the bar window and stores a grade."""
    c, _ = client
    # seed demo bars so the detector window is populated
    bars = [{"t": 1715780100 + i * 300, "o": 18000 + i, "h": 18010 + i,
             "l": 17995 + i, "c": 18005 + i, "v": 500} for i in range(8)]
    assert c.post("/webhooks/pine", json={"source": "pine", "symbol": "NQ",
                  "timeframe": "5", "bars": bars}).json()["bars_added"] == 8
    # log a demo trade (auth-gated)
    h = {"Authorization": "Bearer secret"}
    assert c.post("/api/trades", headers=h, json={
        "side": "long", "realized_r": 2.0, "killzone": "ny_am", "path_clean": True,
    }).status_code == 200
    # it shows in the journal with an auto grade
    trades = c.get("/api/trades?mode=demo").json()
    assert len(trades) == 1 and trades[0]["analysis_grade"] in {"A", "B", "C", "D"}
    tid = trades[0]["id"]
    # the detail endpoint returns the 6-element breakdown; killzone+path are present
    a = c.get(f"/api/trades/{tid}/analysis").json()
    assert a["score"] >= 0.25 and len(a["elements"]) == 6
    assert any(e["name"] == "Killzone timing" and e["present"] for e in a["elements"])
    assert any(e["name"] == "Clean path (LRLR)" and e["present"] for e in a["elements"])
    # unknown trade -> 404
    assert c.get("/api/trades/99999/analysis").status_code == 404


def test_dataset_preview_and_export(client):
    """Trades flatten into a labeled training dataset, downloadable as jsonl/csv."""
    c, _ = client
    h = {"Authorization": "Bearer secret"}
    c.post("/api/trades", headers=h, json={"side": "long", "realized_r": 2.0, "killzone": "ny_am"})
    c.post("/api/trades", headers=h, json={
        "side": "short", "realized_r": -1.0, "moved_to_be_early": True})
    preview = c.get("/api/dataset?mode=demo").json()
    assert preview["n"] == 2
    for col in ("win", "realized_r", "el_killzone", "analysis_grade", "moved_to_be_early"):
        assert col in preview["columns"]
    # jsonl: one parseable object per trade, with the outcome label
    jl = c.get("/api/dataset/export?mode=demo&format=jsonl")
    assert jl.status_code == 200
    lines = [ln for ln in jl.text.splitlines() if ln.strip()]
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert "win" in rec and "realized_r" in rec
    # csv: header + 2 data rows
    csv_resp = c.get("/api/dataset/export?mode=demo&format=csv")
    assert csv_resp.status_code == 200
    csv_lines = csv_resp.text.splitlines()
    assert csv_lines[0].startswith("trade_id,") and len(csv_lines) == 3


def test_log_entry_click_uses_clicked_window_and_grades(client):
    """The click-to-log tool logs a demo trade at the clicked bar time and grades it."""
    c, _ = client
    # seed bars whose timestamps the click will reference
    base = 1715780100
    bars = [{"t": base + i * 300, "o": 18000 + i, "h": 18010 + i,
             "l": 17995 + i, "c": 18005 + i, "v": 500} for i in range(8)]
    c.post("/webhooks/pine", json={"source": "pine", "symbol": "NQ", "timeframe": "5", "bars": bars})
    click_ts = base + 6 * 300  # click the 7th candle
    h = {"Authorization": "Bearer secret"}
    # unauth -> 401
    assert c.post("/api/log-entry", json={"entry_ts": str(click_ts)}).status_code == 401
    r = c.post("/api/log-entry", headers=h, json={
        "entry_ts": str(click_ts), "entry_px": 18030.0, "side": "long", "realized_r": 1.5,
        "moved_to_be_early": False})
    assert r.status_code == 200 and r.json()["ok"] is True
    # it lands under demo at the clicked time (not "now") with an auto grade
    trades = c.get("/api/trades?mode=demo").json()
    assert len(trades) == 1
    assert trades[0]["entry_ts"].startswith("2024-05-15")  # the clicked bar's date, not today
    assert trades[0]["analysis_grade"] in {"A", "B", "C", "D"}


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
