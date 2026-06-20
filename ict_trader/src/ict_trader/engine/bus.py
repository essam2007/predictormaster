"""A tiny in-process async pub/sub bus for engine events."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    async def publish(self, topic: str, event: Any) -> None:
        handlers = self._subs.get(topic, [])
        if handlers:
            await asyncio.gather(*(h(event) for h in handlers))
