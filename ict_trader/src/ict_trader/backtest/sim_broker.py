"""Simulated broker for backtests.

This is the *batch* face of the same machine the live engine uses: it feeds the future
bars into a streaming :class:`PaperBroker` one at a time, so backtest fills/management are
identical to paper trading. Entry fills as a limit into the IFVG; the corrected breakeven /
runner logic comes from the shared PositionManager.
"""

from __future__ import annotations

from ..domain.bars import Bar
from ..domain.enums import Symbol, TradeMode
from ..domain.signals import EntryIntent
from ..domain.trades import Trade
from ..execution.paper_broker import PaperBroker


class SimBroker:
    def __init__(
        self,
        *,
        point_value: float,
        slippage_points: float = 0.25,
        mode: TradeMode = TradeMode.BACKTEST,
    ) -> None:
        self.point_value = point_value
        self.slippage = slippage_points
        self.mode = mode
        self._paper = PaperBroker(point_value=point_value, slippage_points=slippage_points,
                                  mode=mode)
        self.trades: list[Trade] = self._paper.trades

    def run_position(
        self, intent: EntryIntent, qty: int, future_bars: list[Bar], symbol: Symbol
    ) -> Trade | None:
        """Simulate a position from entry to exit over ``future_bars`` (the traded symbol)."""
        pp = self._paper.open(intent, qty, symbol)
        for bar in future_bars:
            self._paper.on_bar(pp, bar)
            if pp.closed:
                return pp.trade
            if pp.dead:
                return None
        # ran out of data while still open -> mark to the last close
        if pp.entered and not pp.closed and future_bars:
            return self._paper.force_close(pp, future_bars[-1])
        return None
