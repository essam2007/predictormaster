"""Tradovate WebSocket user-sync client (fills / orders / positions).

Tradovate's WS frames use a compact ``<op>\n<id>\n<query>\n<body>`` text protocol and an
``o`` open frame / ``h`` heartbeat. This client authorizes, subscribes to user sync, and
yields parsed events; the runtime maps fills back to managed positions. Kept minimal and
dependency-light; reconnection is driven by the runtime via ``reconcile``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import websockets


class TradovateWS:
    def __init__(self, url: str, access_token: str) -> None:
        self.url = url
        self.access_token = access_token
        # websockets renamed its connection type across versions; keep it untyped here.
        self._ws: Any = None
        self._req_id = 0
        self._on_event: Callable[[dict], None] | None = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(self.url, open_timeout=10)
        # Tradovate sends an 'o' frame on open; then we authorize.
        await self._ws.recv()
        await self._send("authorize", "", self.access_token)

    async def _send(self, endpoint: str, query: str, body: str) -> int:
        assert self._ws is not None
        self._req_id += 1
        frame = f"{endpoint}\n{self._req_id}\n{query}\n{body}"
        await self._ws.send(frame)
        return self._req_id

    async def subscribe_user_sync(self, account_id: int) -> None:
        await self._send("user/syncrequest", "", json.dumps({"accounts": [account_id]}))

    async def heartbeats(self) -> None:
        """Reply to server heartbeats with '[]' frames (Tradovate keepalive)."""
        while self._ws is not None:
            await asyncio.sleep(2.5)
            try:
                await self._ws.send("[]")
            except websockets.ConnectionClosed:
                return

    async def events(self) -> AsyncIterator[dict]:
        assert self._ws is not None
        async for raw in self._ws:
            if not raw or raw in ("h", "o"):  # heartbeat / open
                continue
            try:
                # 'a' frames carry a JSON array of events after the leading 'a'.
                payload = raw[1:] if raw[0] == "a" else raw
                for event in json.loads(payload):
                    yield event
            except (ValueError, IndexError):
                continue

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
