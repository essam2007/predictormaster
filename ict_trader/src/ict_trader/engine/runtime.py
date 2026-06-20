"""The live async engine: feed -> pipeline -> risk/kill-switch -> executor -> store.

In ``dry_run`` mode (default) it computes and logs everything but never sends an order — the
paper/monitor mode used in Phase 2. Wiring a real ``TradovateREST`` and clearing dry_run
arms execution (demo endpoint first).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ..clock import ET
from ..config import INSTRUMENTS
from ..domain.bars import Bar
from ..domain.enums import Symbol, TradeMode
from ..domain.signals import EntryIntent
from ..execution.kill_switch import KillSwitch
from ..execution.order_router import build_bracket
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
    repo_factory: object | None = None  # async callable -> Repository context
    mode: TradeMode = TradeMode.DEMO
    dry_run: bool = True
    _cur_date: object = field(default=None, init=False)

    async def run(self, feed_stream: AsyncIterator[Bar]) -> None:
        traded = self.pipeline.traded
        point_value = INSTRUMENTS[traded].point_value
        async for m1 in feed_stream:
            self._roll_day(m1)
            results = self.pipeline.on_minute_bar(m1)
            for snap, intent in results:
                await self.bus.publish("setup", snap)
                if intent is not None and snap.gated_pass:
                    await self._handle_intent(intent, traded, point_value)

    def _roll_day(self, m1: Bar) -> None:
        d = m1.ts_open.astimezone(ET).date()
        if self._cur_date != d:
            self.risk.reset_day()
            self._cur_date = d

    async def _handle_intent(self, intent: EntryIntent, traded: Symbol, point_value: float) -> None:
        if not self.kill.can_trade():
            log.warning("kill switch active (%s); skipping intent", self.kill.reason)
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
            log.info("[DRY-RUN] would place %s %d %s bracket @ %.2f stop %.2f",
                     intent.side.value, qty, traded.value, intent.entry_px, intent.stop_px)
            return
        try:
            await self.executor.place_bracket(spec)  # type: ignore[attr-defined]
            self.risk.on_open()
        except Exception as exc:  # noqa: BLE001
            log.exception("order placement failed: %s", exc)
            self.kill.on_order_reject()
