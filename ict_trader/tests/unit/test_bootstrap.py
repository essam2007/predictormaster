from __future__ import annotations

import pytest

pytest.importorskip("httpx", reason="requires the [serve] extra")

from ict_trader import config  # noqa: E402
from ict_trader.config import Settings  # noqa: E402
from ict_trader.engine.bootstrap import build_live_feed, start_demo_engine  # noqa: E402


def _no_creds(monkeypatch):
    config.get_tradovate_settings.cache_clear()
    for k in ("TRADOVATE_NAME", "TRADOVATE_PASSWORD", "TRADOVATE_CID", "TRADOVATE_SECRET"):
        monkeypatch.delenv(k, raising=False)


def test_build_live_feed_returns_none_without_creds(monkeypatch):
    _no_creds(monkeypatch)
    feed, rest = build_live_feed(Settings(_env_file=None))
    assert feed is None and rest is None


async def test_start_demo_engine_noop_when_autostart_disabled(monkeypatch):
    monkeypatch.delenv("ICT_TRADER_ENGINE_AUTOSTART", raising=False)
    task = await start_demo_engine(Settings(_env_file=None), db=None)
    assert task is None  # never touches creds/db when disabled


async def test_start_demo_engine_noop_without_creds(monkeypatch):
    monkeypatch.setenv("ICT_TRADER_ENGINE_AUTOSTART", "true")
    _no_creds(monkeypatch)
    task = await start_demo_engine(Settings(_env_file=None), db=None)
    assert task is None  # autostart on but no creds -> skip, don't crash
