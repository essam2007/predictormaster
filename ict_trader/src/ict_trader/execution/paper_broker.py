"""Streaming paper broker: manages a single position bar-by-bar.

Used by the live engine in paper/dry-run mode and by the batch backtest broker (which just
feeds it the future bars in order). One streaming state machine = identical behaviour live
and in backtest. Fills are simulated; the corrected breakeven / runner logic comes straight
from :class:`PositionManager`.
"""

from __future__ import annotations

from ..detectors.structure import StructureView, analyze
from ..domain.bars import Bar
from ..domain.enums import BreakevenTrigger, ExitReason, Side, Symbol, TradeMode
from ..domain.signals import EntryIntent
from ..domain.trades import Trade
from . import fills
from .position_manager import ManagedPosition, PositionManager


class PaperPosition:
    """Tracks one position's lifecycle as bars stream in."""

    def __init__(self, intent: EntryIntent, qty: int, symbol: Symbol, point_value: float,
                 mode: TradeMode, slippage: float) -> None:
        self.intent = intent
        self.qty = qty
        self.symbol = symbol
        self.point_value = point_value
        self.mode = mode
        self.slippage = slippage
        self.entered = False
        self.dead = False  # invalidated before entry
        self.pos: ManagedPosition | None = None
        self.qty_remaining = qty
        self.realized_points = 0.0
        self.trade: Trade | None = None
        self._recent: list[Bar] = []

    @property
    def closed(self) -> bool:
        return self.trade is not None and not self.trade.is_open


def _structure_window(recent: list[Bar], side: Side) -> StructureView:
    return analyze(recent, side)


class PaperBroker:
    def __init__(self, *, point_value: float, slippage_points: float = 0.25,
                 mode: TradeMode = TradeMode.DEMO, window: int = 40) -> None:
        self.point_value = point_value
        self.slippage = slippage_points
        self.mode = mode
        self.window = window
        self.pm = PositionManager()
        self.trades: list[Trade] = []

    def open(self, intent: EntryIntent, qty: int, symbol: Symbol) -> PaperPosition:
        return PaperPosition(intent, qty, symbol, self.point_value, self.mode, self.slippage)

    def on_bar(self, pp: PaperPosition, bar: Bar) -> Trade | None:
        """Advance one position by one (closed, traded-symbol) bar. Returns the Trade on close."""
        if pp.closed or pp.dead:
            return pp.trade
        intent = pp.intent
        side = intent.side
        pp._recent.append(bar)
        if len(pp._recent) > self.window:
            pp._recent = pp._recent[-self.window :]

        # --- pre-entry: wait for the limit to be touched ---
        if not pp.entered:
            if fills.touches(bar, intent.entry_px):
                pp.entered = True
                pp.pos = ManagedPosition(intent=intent, qty=pp.qty, entry_px=intent.entry_px,
                                         stop_px=intent.stop_px, side=side)
                pp.trade = Trade(
                    symbol=pp.symbol, side=side, entry_ts=bar.ts_open, entry_px=intent.entry_px,
                    qty_initial=pp.qty, mode=self.mode,
                    risk_per_contract=pp.pos.risk * self.point_value,
                    setup_score=intent.setup.score, killzone=intent.setup.killzone,
                    quarter_idx=intent.setup.quarter_idx, amd_phase=intent.setup.amd_phase,
                    path_clean=intent.setup.path_clean, day_of_week=bar.ts_open.weekday(),
                )
                return None
            if fills.adverse_first(side, bar, intent.entry_px, intent.stop_px):
                pp.dead = True
            return None

        # --- post-entry: manage ---
        assert pp.pos is not None and pp.trade is not None
        struct = _structure_window(pp._recent, side)
        decision = self.pm.on_bar(pp.pos, bar, struct)
        if decision.new_stop is not None:
            pp.pos.stop_px = decision.new_stop
        if decision.take_partial_qty > 0 and decision.level is not None:
            pp.realized_points += fills.pnl_points(side, pp.pos.entry_px, decision.level) * decision.take_partial_qty
            pp.qty_remaining -= decision.take_partial_qty
            pp.pos.qty_remaining = pp.qty_remaining
            pp.pos.partials_taken += 1
            pp.trade.partials_taken += 1
        if decision.exit_all:
            fill_px = fills.exit_fill_px(side, bar, decision.exit_reason,
                                         stop_px=pp.pos.stop_px,
                                         runner_target_px=intent.runner_target_px,
                                         slippage=self.slippage)
            pp.realized_points += fills.pnl_points(side, pp.pos.entry_px, fill_px) * pp.qty_remaining
            pp.qty_remaining = 0
            self._finalize(pp, bar.ts_open, fill_px, decision.exit_reason)
            return pp.trade
        return None

    def force_close(self, pp: PaperPosition, bar: Bar, reason: ExitReason = ExitReason.MANUAL) -> Trade | None:
        """Close any remaining quantity at the bar close (end of data / kill switch)."""
        if not pp.entered or pp.closed or pp.pos is None or pp.trade is None:
            return pp.trade
        pp.realized_points += (
            fills.pnl_points(pp.intent.side, pp.pos.entry_px, bar.close) * pp.qty_remaining
        )
        pp.qty_remaining = 0
        self._finalize(pp, bar.ts_open, bar.close, reason)
        return pp.trade

    def _finalize(self, pp: PaperPosition, ts, exit_px: float, reason: ExitReason | None) -> None:
        assert pp.pos is not None and pp.trade is not None
        t = pp.trade
        t.exit_ts = ts
        t.exit_px = exit_px
        t.exit_reason = reason
        t.runner_held = pp.pos.partials_taken > 0
        t.runner_hit_erl = reason is ExitReason.RUNNER_TARGET
        t.moved_to_be_early = pp.pos.moved_to_be_early
        t.be_trigger = pp.pos.be_trigger or BreakevenTrigger.NONE
        t.realized_pnl = pp.realized_points * self.point_value
        risk_pts = pp.pos.risk if pp.pos.risk > 0 else 1e-9
        t.realized_r = round((pp.realized_points / pp.qty if pp.qty else 0) / risk_pts, 3)
        t.mfe_r = round(pp.pos.mfe / risk_pts, 3)
        t.mae_r = round(pp.pos.mae / risk_pts, 3)
        t.events = pp.pos.events
        self.trades.append(t)
