from __future__ import annotations

import pytest

pytest.importorskip("websockets", reason="requires the [serve] extra")

from ict_trader.domain.enums import Symbol, Timeframe  # noqa: E402
from ict_trader.marketdata.tradovate_md import (  # noqa: E402
    bars_from_event,
    extract_events,
    parse_chart_bars,
    parse_ts,
)


def test_parse_ts_iso_and_epoch():
    a = parse_ts("2024-05-15T13:30:00.000Z")
    assert a.year == 2024 and a.hour == 13 and a.tzinfo is not None
    b = parse_ts(1715780000)
    assert b.tzinfo is not None


def test_parse_chart_bars():
    bars = parse_chart_bars([
        {"timestamp": "2024-05-15T13:30:00Z", "open": 100, "high": 101, "low": 99,
         "close": 100.5, "upVolume": 10, "downVolume": 5},
    ], Symbol.NQ)
    assert len(bars) == 1
    b = bars[0]
    assert b.symbol is Symbol.NQ and b.timeframe is Timeframe.M1
    assert b.open == 100 and b.high == 101 and b.low == 99 and b.close == 100.5
    assert b.volume == 15 and b.is_closed is True


def test_extract_events_handles_open_and_heartbeat():
    assert extract_events("o") == []
    assert extract_events("h") == []
    assert extract_events('a[{"e":"chart"}]') == [{"e": "chart"}]


def test_bars_from_event_maps_subid_to_symbol():
    event = {"e": "chart", "d": {"charts": [
        {"id": 7, "bars": [{"timestamp": "2024-05-15T13:31:00Z", "open": 1, "high": 2,
                            "low": 0.5, "close": 1.5}]},
    ]}}
    bars = bars_from_event(event, {7: Symbol.ES})
    assert len(bars) == 1 and bars[0].symbol is Symbol.ES
    # unknown subid -> no bars
    assert bars_from_event(event, {99: Symbol.ES}) == []
