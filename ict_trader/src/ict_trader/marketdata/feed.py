"""The MarketFeed protocol shared by live feeds and the backtest replay source.

Every feed yields 1-minute bars per symbol in time order; the engine aggregates them into
higher timeframes. Keeping a single protocol is what lets the backtester run the identical
engine code path as live.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from ..domain.bars import Bar


@runtime_checkable
class MarketFeed(Protocol):
    async def stream(self) -> AsyncIterator[Bar]:
        """Yield closed 1-minute bars (ES and NQ interleaved) in non-decreasing time."""
        ...
