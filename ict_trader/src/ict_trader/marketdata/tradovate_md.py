"""Tradovate market-data feed implementing the MarketFeed protocol.

Authenticates via the REST client (for ``mdAccessToken``), opens the market-data WebSocket,
requests a 1-minute chart for ES and NQ, and yields closed 1-minute :class:`Bar`s. The
engine aggregates those into higher timeframes exactly as it does for replay, so live and
backtest share one code path.

The frame-parsing helpers are pure and unit-tested. The exact ``md/getChart`` packet shape
can vary by API version; ``parse_chart_bars`` is the single place to adjust if a field
name differs on your account.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from zoneinfo import ZoneInfo

import websockets

from ..domain.bars import Bar
from ..domain.enums import Symbol, Timeframe

UTC = ZoneInfo("UTC")


def parse_ts(raw: str | int | float) -> datetime:
    """Parse a Tradovate bar timestamp (ISO-8601 UTC or epoch seconds) to tz-aware UTC."""
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC)
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(UTC)


def parse_chart_bars(bars_json: list[dict], symbol: Symbol) -> list[Bar]:
    """Convert Tradovate chart bar dicts into closed 1-minute Bars."""
    out: list[Bar] = []
    for b in bars_json:
        ts = b.get("timestamp") or b.get("t")
        if ts is None:
            continue
        vol = float(b.get("upVolume", 0) or 0) + float(b.get("downVolume", 0) or 0)
        out.append(Bar(
            symbol=symbol, timeframe=Timeframe.M1, ts_open=parse_ts(ts),
            open=float(b["open"]), high=float(b["high"]), low=float(b["low"]),
            close=float(b["close"]), volume=vol, is_closed=True,
        ))
    return out


def extract_events(frame: str) -> list[dict]:
    """Tradovate 'a' frames carry a JSON array of events after the leading 'a'."""
    if not frame or frame in ("o", "h"):
        return []
    try:
        payload = frame[1:] if frame[0] == "a" else frame
        data = json.loads(payload)
        return data if isinstance(data, list) else [data]
    except (ValueError, IndexError):
        return []


def bars_from_event(event: dict, symbol_by_subid: dict[int, Symbol]) -> list[Bar]:
    """Pull bars out of a chart event, mapping its subscription id to a symbol."""
    if event.get("e") != "chart":
        return []
    out: list[Bar] = []
    for chart in event.get("d", {}).get("charts", []):
        sym = symbol_by_subid.get(chart.get("id"))
        if sym is None:
            continue
        out.extend(parse_chart_bars(chart.get("bars", []), sym))
    return out


class TradovateMarketData:
    """Streams ES + NQ 1-minute bars from Tradovate's market-data WebSocket."""

    def __init__(self, rest, md_ws_url: str, es_symbol: str = "ES", nq_symbol: str = "NQ",
                 history_bars: int = 300) -> None:
        self.rest = rest
        self.md_ws_url = md_ws_url
        self.symbols = {es_symbol: Symbol.ES, nq_symbol: Symbol.NQ}
        self.history_bars = history_bars
        self._req_id = 0
        self._subid_to_symbol: dict[int, Symbol] = {}

    async def _send(self, ws, endpoint: str, body: str) -> int:
        self._req_id += 1
        await ws.send(f"{endpoint}\n{self._req_id}\n\n{body}")
        return self._req_id

    def _chart_request(self, contract: str) -> str:
        return json.dumps({
            "symbol": contract,
            "chartDescription": {"underlyingType": "MinuteBar", "elementSize": 1,
                                 "elementSizeUnit": "UnderlyingUnits"},
            "timeRange": {"asMuchAsElements": self.history_bars},
        })

    async def stream(self) -> AsyncIterator[Bar]:
        await self.rest.ensure_token()
        md_token = self.rest.md_access_token or self.rest.access_token
        async with websockets.connect(self.md_ws_url, open_timeout=10) as ws:
            await ws.recv()  # 'o' open frame
            await self._send(ws, "authorize", md_token)
            # request a realtime 1-minute chart per contract
            for contract in self.symbols:
                req_id = await self._send(ws, "md/getChart", self._chart_request(contract))
                self._subid_to_symbol[req_id] = self.symbols[contract]
            asyncio.create_task(self._heartbeat(ws))
            async for frame in ws:
                text = frame.decode() if isinstance(frame, bytes) else frame
                for event in extract_events(text):
                    # map the realtime chart id from the getChart ack if present
                    self._maybe_map_realtime(event)
                    for bar in bars_from_event(event, self._subid_to_symbol):
                        yield bar

    def _maybe_map_realtime(self, event: dict) -> None:
        # md/getChart acks return {"i": req_id, "d": {"realtimeId": <id>}}; map it to the
        # same symbol so realtime chart packets resolve.
        rid = event.get("i")
        realtime_id = event.get("d", {}).get("realtimeId") if isinstance(event.get("d"), dict) else None
        if rid in self._subid_to_symbol and realtime_id is not None:
            self._subid_to_symbol[realtime_id] = self._subid_to_symbol[rid]

    async def _heartbeat(self, ws) -> None:
        try:
            while True:
                await asyncio.sleep(2.5)
                await ws.send("[]")
        except (websockets.ConnectionClosed, RuntimeError):
            return
