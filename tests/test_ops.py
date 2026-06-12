"""Tests for the ops dashboard: metrics, runner manager, balance helpers,
and the FastAPI endpoints.

Network-touching code (Polygon RPC) is replaced with a stub via
monkeypatching — no real HTTP goes out from tests.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from predictormaster.ops import balance as balance_mod
from predictormaster.ops.metrics import (
    compute_metrics,
    load_decisions,
    recent_decisions,
)
from predictormaster.ops.runner import LIVE_CONFIRMATION_TOKEN, RunnerManager

# ---------------- metrics ----------------

def _write_journal(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_load_decisions_skips_malformed_lines(tmp_path: Path) -> None:
    journal = tmp_path / "decisions.jsonl"
    journal.write_text(
        '{"timestamp":"2026-05-15T10:00:00Z","alpha":"a2","token_id":"x","side":"BUY",'
        '"mode":"shadow","accepted":false,"rejection_reason":"min_edge",'
        '"requested_size":10,"requested_price":0.45}\n'
        '{ not valid json\n'
        '\n'
        '{"timestamp":"2026-05-15T10:00:01Z","alpha":"a2","token_id":"x","side":"SELL",'
        '"mode":"paper","accepted":true,"requested_size":2,"requested_price":0.5,'
        '"pnl_usd":0.03}\n'
    )
    rows = load_decisions(journal)
    assert len(rows) == 2
    assert rows[0].mode == "shadow"
    assert rows[1].pnl_usd == pytest.approx(0.03)


def test_compute_metrics_aggregates_by_mode(tmp_path: Path) -> None:
    journal = tmp_path / "decisions.jsonl"
    rows = [
        # shadow: 3 rejected, no PnL
        *[{"alpha": "α2", "mode": "shadow", "accepted": False,
           "rejection_reason": "min_edge",
           "requested_size": 5, "requested_price": 0.4,
           "timestamp": f"t{i}"} for i in range(3)],
        # paper: 2 fills, one winning
        {"alpha": "α2", "mode": "paper", "accepted": True,
         "requested_size": 4, "requested_price": 0.25, "pnl_usd": 0.50,
         "timestamp": "t10"},
        {"alpha": "α2", "mode": "paper", "accepted": True,
         "requested_size": 4, "requested_price": 0.25, "pnl_usd": -0.10,
         "timestamp": "t11"},
        # live: 1 fill, win
        {"alpha": "α2", "mode": "live", "accepted": True,
         "requested_size": 2, "requested_price": 0.5, "pnl_usd": 0.20,
         "timestamp": "t12"},
    ]
    _write_journal(journal, rows)
    rows = load_decisions(journal)
    m = compute_metrics(rows)
    assert m["n_decisions_total"] == 6
    assert m["by_mode"]["shadow"]["n_decisions"] == 3
    assert m["by_mode"]["shadow"]["n_accepted"] == 0
    assert m["by_mode"]["paper"]["total_pnl_usd"] == pytest.approx(0.40)
    assert m["by_mode"]["paper"]["win_rate"] == pytest.approx(0.5)
    # aggregate covers paper + live realised fills
    assert m["aggregate_paper_plus_live"]["n_fills_with_pnl"] == 3
    assert m["aggregate_paper_plus_live"]["total_pnl_usd"] == pytest.approx(0.60)


def test_compute_metrics_sharpe_requires_min_sample(tmp_path: Path) -> None:
    # Only 4 fills — below the 5-fill threshold for Sharpe.
    rows = [{"alpha": "α2", "mode": "paper", "accepted": True,
             "requested_size": 1, "requested_price": 0.5, "pnl_usd": 0.1,
             "timestamp": f"t{i}"} for i in range(4)]
    journal = tmp_path / "j.jsonl"
    _write_journal(journal, rows)
    m = compute_metrics(load_decisions(journal))
    assert m["by_mode"]["paper"]["per_bet_sharpe_ann"] is None


def test_recent_decisions_returns_newest_first(tmp_path: Path) -> None:
    rows = [{"alpha": "α2", "mode": "shadow", "accepted": False,
             "requested_size": 1, "requested_price": 0.5,
             "timestamp": f"2026-05-15T10:00:{i:02d}Z"} for i in range(20)]
    journal = tmp_path / "j.jsonl"
    _write_journal(journal, rows)
    decisions_out = recent_decisions(load_decisions(journal), limit=5)
    assert len(decisions_out) == 5
    # Newest first → timestamps in descending order
    times = [d["timestamp"] for d in decisions_out]
    assert times == sorted(times, reverse=True)


# ---------------- balance ----------------

def test_balance_returns_empty_when_rpc_fails(monkeypatch) -> None:
    monkeypatch.delenv("POLY_PROXY_ADDRESS", raising=False)
    monkeypatch.delenv("POLY_FUNDER_PK", raising=False)
    snap = balance_mod.fetch_balances()
    # No addresses configured → nothing to fetch
    assert snap.proxy_pusd is None
    assert snap.proxy_usdc is None
    assert snap.eoa_matic is None


def test_balance_uses_rpc_when_proxy_set(monkeypatch) -> None:
    monkeypatch.setenv("POLY_PROXY_ADDRESS", "0x" + "1" * 40)
    monkeypatch.delenv("POLY_FUNDER_PK", raising=False)
    captured: list[tuple] = []
    def fake_rpc(method, params, *, timeout=4.0):
        captured.append((method, params))
        return {"result": hex(15_000_000)}      # 15.0 USDC at 6 decimals
    monkeypatch.setattr(balance_mod, "_rpc_call", fake_rpc)
    snap = balance_mod.fetch_balances()
    assert snap.proxy_usdc == pytest.approx(15.0)
    # exactly one eth_call to the USDC contract
    assert any(m == "eth_call" for m, _ in captured)


def test_encoded_balance_call_pads_address_correctly() -> None:
    data = balance_mod._encoded_balance_call("0x" + "ab" * 20)
    assert data.startswith("0x70a08231")
    # 4-byte selector + 32-byte padded address = 4 + 32 = 36 bytes = 72 hex
    assert len(data) == 2 + 8 + 64       # "0x" + selector + padded arg
    assert data.endswith("ab" * 20)


# ---------------- runner manager ----------------

@pytest.fixture
def runner_root(tmp_path: Path) -> Path:
    """Project root with a tiny stand-in for scripts/live_runner.py.

    The stand-in just sleeps so we can exercise start/stop without
    importing the real runner (which talks to Polymarket).
    """
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "live_runner.py").write_text(
        "import sys, time\n"
        "print('stub runner starting', flush=True)\n"
        "try:\n"
        "    while True: time.sleep(0.5)\n"
        "except KeyboardInterrupt:\n"
        "    sys.exit(0)\n"
    )
    return tmp_path


def test_runner_starts_and_stops(runner_root: Path) -> None:
    rm = RunnerManager(project_root=runner_root)
    st = rm.start(mode="shadow", bankroll=15, max_stake=2,
                  min_edge=0.005, interval=5)
    assert st["pid"] is not None
    # give the subprocess a moment to start
    time.sleep(0.5)
    assert rm.status()["running"]
    out = rm.stop()
    assert out["stopped"] is True
    assert rm.status()["running"] is False


def test_runner_rejects_live_without_token(runner_root: Path) -> None:
    rm = RunnerManager(project_root=runner_root)
    with pytest.raises(PermissionError):
        rm.start(mode="live", bankroll=15, max_stake=2,
                 min_edge=0.005, interval=5, confirmation=None)
    with pytest.raises(PermissionError):
        rm.start(mode="live", bankroll=15, max_stake=2,
                 min_edge=0.005, interval=5, confirmation="not the token")


def test_runner_accepts_live_with_correct_token(runner_root: Path) -> None:
    rm = RunnerManager(project_root=runner_root)
    rm.start(mode="live", bankroll=15, max_stake=2,
             min_edge=0.005, interval=5,
             confirmation=LIVE_CONFIRMATION_TOKEN)
    time.sleep(0.3)
    rm.stop()


def test_runner_rejects_double_start(runner_root: Path) -> None:
    rm = RunnerManager(project_root=runner_root)
    rm.start(mode="shadow", bankroll=15, max_stake=2,
             min_edge=0.005, interval=5)
    time.sleep(0.3)
    with pytest.raises(RuntimeError):
        rm.start(mode="shadow", bankroll=15, max_stake=2,
                 min_edge=0.005, interval=5)
    rm.stop()


def test_runner_rejects_invalid_params(runner_root: Path) -> None:
    rm = RunnerManager(project_root=runner_root)
    with pytest.raises(ValueError):
        rm.start(mode="bogus", bankroll=15, max_stake=2,
                 min_edge=0.005, interval=5)
    with pytest.raises(ValueError):
        rm.start(mode="shadow", bankroll=0, max_stake=2,
                 min_edge=0.005, interval=5)
    with pytest.raises(ValueError):
        rm.start(mode="shadow", bankroll=15, max_stake=2,
                 min_edge=0.005, interval=1)         # < 5s


def test_runner_state_survives_manager_restart(runner_root: Path) -> None:
    rm1 = RunnerManager(project_root=runner_root)
    st = rm1.start(mode="shadow", bankroll=15, max_stake=2,
                   min_edge=0.005, interval=5)
    pid = st["pid"]
    time.sleep(0.3)
    # simulate server restart: new manager instance, same root
    rm2 = RunnerManager(project_root=runner_root)
    assert rm2.status()["pid"] == pid
    assert rm2.status()["running"]
    rm2.stop()


# ---------------- FastAPI endpoints ----------------

def test_app_endpoints_smoke(monkeypatch, tmp_path: Path) -> None:
    fastapi = pytest.importorskip("fastapi")
    _ = fastapi
    from fastapi.testclient import TestClient

    from predictormaster.ops.app import create_app

    # Stub Polygon RPC so balance endpoint doesn't hit the network
    monkeypatch.setattr(balance_mod, "_rpc_call",
                        lambda *a, **k: {"result": hex(15_000_000)})
    monkeypatch.setenv("POLY_PROXY_ADDRESS", "0x" + "1" * 40)
    monkeypatch.delenv("POLY_FUNDER_PK", raising=False)

    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/status")
        assert r.status_code == 200
        body = r.json()
        assert body["live_confirmation_token"] == LIVE_CONFIRMATION_TOKEN
        assert "runner" in body and "kill_switch" in body

        r = client.get("/api/balance")
        assert r.status_code == 200

        r = client.get("/api/metrics")
        assert r.status_code == 200
        assert "by_mode" in r.json()

        r = client.get("/api/decisions?limit=10")
        assert r.status_code == 200


def test_app_rejects_live_start_without_token(monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from predictormaster.ops.app import create_app

    monkeypatch.setattr(balance_mod, "_rpc_call",
                        lambda *a, **k: {"result": "0x0"})
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/api/start", json={
            "mode": "live", "bankroll": 15, "max_stake": 2,
            "min_edge": 0.005, "interval": 30,
        })
        # 403 — missing confirmation
        assert r.status_code == 403


def test_app_input_validation(monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from predictormaster.ops.app import create_app

    monkeypatch.setattr(balance_mod, "_rpc_call",
                        lambda *a, **k: {"result": "0x0"})
    app = create_app()
    with TestClient(app) as client:
        # interval too low (< 5) — caught by pydantic
        r = client.post("/api/start", json={
            "mode": "shadow", "bankroll": 15, "max_stake": 2,
            "min_edge": 0.005, "interval": 1,
        })
        assert r.status_code == 422
        # invalid mode
        r = client.post("/api/start", json={
            "mode": "bogus", "bankroll": 15, "max_stake": 2,
            "min_edge": 0.005, "interval": 30,
        })
        assert r.status_code == 422
