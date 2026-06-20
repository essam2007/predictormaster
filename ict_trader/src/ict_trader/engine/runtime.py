"""The live async engine: feed -> pipeline -> risk/kill-switch -> broker -> store.

Default mode is PAPER (dry-run): it computes setups, simulates fills with the streaming
PaperBroker, manages each position with the corrected breakeven/runner logic, and emits
closed trades on the bus — exactly the Phase-2 paper loop, feeding the research deck. When
``dry_run`` is cleared and a Tradovate executor is wired, gated intents are sent to the
broker instead (demo endpoint first).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ..clock import ET
from ..config import INSTRUMENTS
from ..domain.bars import Bar
from ..domain.enums import Symbol, Timeframe, TradeMode
from ..domain.signals import EntryIntent
from ..domain.trades import Trade
from ..execution.kill_switch import KillSwitch
from ..execution.order_router import build_bracket
from ..execution.paper_broker import PaperBroker, PaperPosition
from ..execution.risk import RiskEngine
from .bus import EventBus
from .pipeline import SignalPipeline

log = logging.getLogger("ict_trader.runtime")


@dataclass
class LiveEngine:
    pipeline: SignalPipeline
    risk: RiskEngine
    kill: KillSwitch = field(default_factory=KillSwitch)
    bus: EventBus = field(default_factory=EventBus)
    executor: object | None = None  # TradovateREST when armed
    mode: TradeMode = TradeMode.DEMO
    dry_run: bool = True
    setups_seen: int = 0
    closed_trades: list[Trade] = field(default_factory=list)
    _cur_date: object = field(default=None, init=False)
    _open: PaperPosition | None = field(default=None, init=False)
    _broker: PaperBroker | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        pv = INSTRUMENTS[self.pipeline.traded].point_value
        self._broker = PaperBroker(point_value=pv, mode=self.mode)

    async def run(self, feed_stream: AsyncIterator[Bar]) -> None:
        traded = self.pipeline.traded
        point_value = INSTRUMENTS[traded].point_value
        async for m1 in feed_stream:
            self._roll_day(m1)
            results = self.pipeline.on_minute_bar(m1)
            if not results:
                continue
            # a traded trigger bar just closed -> advance any open position with it first
            trigger_bar = self.pipeline.state.closed_bars(traded, Timeframe.M5)[-1]
            await self._advance(trigger_bar)
            for snap, intent in results:
                self.setups_seen += 1
                await self.bus.publish("setup", snap)
                if intent is not None and snap.gated_pass:
                    await self._handle_intent(intent, traded, point_value)

    def _roll_day(self, m1: Bar) -> None:
        d = m1.ts_open.astimezone(ET).date()
        if self._cur_date != d:
            self.risk.reset_day()
            self._cur_date = d

    async def _advance(self, bar: Bar) -> None:
        if self._open is None or self._broker is None:
            return
        if self.kill.active and not self._open.closed:
            trade = self._broker.force_close(self._open, bar)
        else:
            trade = self._broker.on_bar(self._open, bar)
        if self._open.dead:  # invalidated before entry
            self._open = None
            return
        if trade is not None and self._open.closed:
            self.risk.on_close(trade.realized_pnl)
            self.closed_trades.append(trade)
            await self.bus.publish("trade", trade)
            self._open = None

    async def _handle_intent(self, intent: EntryIntent, traded: Symbol, point_value: float) -> None:
        if not self.kill.can_trade():
            log.warning("kill switch active (%s); skipping intent", self.kill.reason)
            return
        if self._open is not None:  # one concurrent position
            return
        ok, reason = self.risk.can_enter()
        if not ok:
            log.info("risk gate blocked entry: %s", reason)
            return
        stop_pts = abs(intent.entry_px - intent.stop_px)
        qty = self.risk.size_for(traded, stop_pts, point_value)
        if qty <= 0:
            log.info("size computed as 0; skipping")
            return
        spec = build_bracket(intent, qty, symbol=traded.value)
        await self.bus.publish("intent", {"intent": intent, "spec": spec})
        if self.dry_run or self.executor is None:
            assert self._broker is not None
            self._open = self._broker.open(intent, qty, traded)
            self.risk.on_open()
            log.info("[PAPER] opened %s %d %s @ %.2f stop %.2f",
                     intent.side.value, qty, traded.value, intent.entry_px, intent.stop_px)
            return
        try:
            await self.executor.place_bracket(spec)  # type: ignore[attr-defined]
            self.risk.on_open()
        except Exception as exc:  # noqa: BLE001
            log.exception("order placement failed: %s", exc)
            self.kill.on_order_reject()
