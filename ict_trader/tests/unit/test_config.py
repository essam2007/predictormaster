from __future__ import annotations

import pytest

from ict_trader.config import LIVE_CONFIRM_PHRASE, Settings


def _clear(monkeypatch):
    for k in ("ICT_TRADER_MODE", "ICT_TRADER_LIVE_CONFIRM"):
        monkeypatch.delenv(k, raising=False)


def test_demo_is_default_and_uses_demo_endpoints(monkeypatch):
    _clear(monkeypatch)
    s = Settings()
    assert s.is_live is False
    assert "demo.tradovateapi.com" in s.tradovate_base_url
    assert "md-demo" in s.tradovate_md_ws


def test_live_requires_confirmation_interlock(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ICT_TRADER_MODE", "live")
    with pytest.raises(ValueError):
        Settings()  # no confirmation -> refuses to arm live


def test_live_allowed_with_confirmation(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ICT_TRADER_MODE", "live")
    monkeypatch.setenv("ICT_TRADER_LIVE_CONFIRM", LIVE_CONFIRM_PHRASE)
    s = Settings()
    assert s.is_live is True
    assert "live.tradovateapi.com" in s.tradovate_base_url
