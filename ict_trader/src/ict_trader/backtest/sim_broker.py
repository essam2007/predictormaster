"""A simulated broker for backtests.

Fills the entry as a limit into the IFVG (filled when price trades to it), then applies the
PositionManager's decisions bar-by-bar with configurable slippage. Emits the same kind of
Trade the live executor would record, so the research deck analyses both identically.
"""

from __future__ import annotations

from ..detectors.structure import analyze
from ..domain.bars import Bar
from ..domain.enums import (
    BreakevenTrigger,
    ExitReason,
    Side,
    Symbol,
    TradeMode,
)
from ..domain.signals import EntryIntent
from ..domain.trades import Trade
from ..execution.position_manager import ManagedPosition, PositionManager


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
        self.pm = PositionManager()
        self.trades: list[Trade] = []

    def run_position(
        self, intent: EntryIntent, qty: int, future_bars: list[Bar], symbol: Symbol
    ) -> Trade | None:
        """Simulate a position from entry to exit over ``future_bars`` (the traded symbol).

        ``future_bars`` are the closed trigger-timeframe bars AFTER the signal bar.
        """
        side = intent.side
        # entry fill: limit must be touched
        entry_filled = False
        bars_iter = iter(enumerate(future_bars))
        entry_idx = -1
        for i, b in bars_iter:
            if self._touches(side, b, intent.entry_px):
                entry_filled = True
                entry_idx = i
                break
            # stop would be hit before entry -> no trade
            if self._adverse_first(side, b, intent.entry_px, intent.stop_px):
                return None
        if not entry_filled:
            return None

        pos = ManagedPosition(intent=intent, qty=qty, entry_px=intent.entry_px,
                              stop_px=intent.stop_px, side=side)
        trade = Trade(
            symbol=symbol, side=side, entry_ts=future_bars[entry_idx].ts_open,
            entry_px=intent.entry_px, qty_initial=qty, mode=self.mode,
            risk_per_contract=pos.risk * self.point_value,
            setup_score=intent.setup.score,
            killzone=intent.setup.killzone, quarter_idx=intent.setup.quarter_idx,
            amd_phase=intent.setup.amd_phase, path_clean=intent.setup.path_clean,
            day_of_week=future_bars[entry_idx].ts_open.weekday(),
        )

        realized_points = 0.0
        qty_remaining = qty
        for b in future_bars[entry_idx + 1 :]:
            struct = analyze(self._window(future_bars, b), side)
            decision = self.pm.on_bar(pos, b, struct)
            if decision.new_stop is not None:
                pos.stop_px = decision.new_stop
                if not pos.breakeven_done:
                    pass
            if decision.take_partial_qty > 0:
                fill_px = self._partial_fill_px(side, b, intent)
                realized_points += self._pnl_points(side, pos.entry_px, fill_px) * decision.take_partial_qty
                qty_remaining -= decision.take_partial_qty
                pos.qty_remaining = qty_remaining
                pos.partials_taken += 1
                trade.partials_taken += 1
            if decision.exit_all:
                fill_px = self._exit_fill_px(side, b, decision.exit_reason, pos)
                realized_points += self._pnl_points(side, pos.entry_px, fill_px) * qty_remaining
                qty_remaining = 0
                trade.exit_ts = b.ts_open
                trade.exit_px = fill_px
                trade.exit_reason = decision.exit_reason
                trade.runner_held = pos.partials_taken > 0
                trade.runner_hit_erl = decision.exit_reason is ExitReason.RUNNER_TARGET
                break

        if qty_remaining > 0:  # ran out of data; mark to last close
            last = future_bars[-1]
            realized_points += self._pnl_points(side, pos.entry_px, last.close) * qty_remaining
            trade.exit_ts = last.ts_open
            trade.exit_px = last.close
            trade.exit_reason = ExitReason.MANUAL

        trade.moved_to_be_early = pos.moved_to_be_early
        trade.be_trigger = pos.be_trigger or BreakevenTrigger.NONE
        trade.realized_pnl = realized_points * self.point_value
        risk_pts = pos.risk if pos.risk > 0 else 1e-9
        trade.realized_r = round((realized_points / qty if qty else 0) / risk_pts, 3)
        trade.mfe_r = round(pos.mfe / risk_pts, 3)
        trade.mae_r = round(pos.mae / risk_pts, 3)
        trade.events = pos.events
        self.trades.append(trade)
        return trade

    # -- fill helpers ----------------------------------------------------
    @staticmethod
    def _touches(side: Side, bar: Bar, level: float) -> bool:
        return bar.low <= level <= bar.high

    @staticmethod
    def _adverse_first(side: Side, bar: Bar, entry: float, stop: float) -> bool:
        # crude: if the bar blows past the stop without ever touching entry
        if side is Side.LONG:
            return bar.high < entry and bar.low <= stop
        return bar.low > entry and bar.high >= stop

    def _partial_fill_px(self, side: Side, bar: Bar, intent: EntryIntent) -> float:
        return intent.tp1_px if not bar else intent.tp1_px  # limit fill at target

    def _exit_fill_px(self, side, bar, reason, pos) -> float:
        if reason in (ExitReason.STOP, ExitReason.TRAIL, ExitReason.BREAKEVEN):
            # stop fills at the stop level minus slippage
            return pos.stop_px - self.slippage if side is Side.LONG else pos.stop_px + self.slippage
        if reason is ExitReason.RUNNER_TARGET:
            return pos.intent.runner_target_px
        return bar.close

    def _pnl_points(self, side: Side, entry: float, exit_px: float) -> float:
        return (exit_px - entry) if side is Side.LONG else (entry - exit_px)

    @staticmethod
    def _window(bars: list[Bar], current: Bar, n: int = 40) -> list[Bar]:
        idx = bars.index(current)
        return bars[max(0, idx - n) : idx + 1]
