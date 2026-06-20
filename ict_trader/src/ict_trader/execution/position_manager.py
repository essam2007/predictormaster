"""Position management — the corrected breakeven / runner logic.

This encodes the single most important fix from the research: we do NOT move to breakeven
on the first pullback. A breakeven/trail move is authorized ONLY after a confirmed
structural break in our favour (BOS/MSS) or a defined displacement leg. We scale out
partials at interim liquidity and hold a runner for the ERL target.

The same class drives both the simulated broker (backtest) and the live executor: it emits
*decisions* (move stop, take partial, exit) that the caller applies to its broker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..detectors.structure import StructureView
from ..domain.bars import Bar
from ..domain.enums import BreakevenTrigger, ExitReason, Side
from ..domain.signals import EntryIntent
from ..domain.trades import ManagementEvent


@dataclass
class ManagedPosition:
    intent: EntryIntent
    qty: int
    entry_px: float
    stop_px: float
    side: Side
    tp1_taken: bool = False
    tp2_taken: bool = False
    qty_remaining: int = 0
    breakeven_done: bool = False
    moved_to_be_early: bool = False
    be_trigger: BreakevenTrigger = BreakevenTrigger.NONE
    partials_taken: int = 0
    mfe: float = 0.0  # favourable excursion in price
    mae: float = 0.0  # adverse excursion in price
    events: list[ManagementEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.qty_remaining == 0:
            self.qty_remaining = self.qty

    @property
    def risk(self) -> float:
        return abs(self.entry_px - self.intent.stop_px)


@dataclass
class ManageDecision:
    take_partial_qty: int = 0
    new_stop: float | None = None
    exit_all: bool = False
    exit_reason: ExitReason | None = None
    note: str = ""


class PositionManager:
    """Stateless-ish manager: call :meth:`on_bar` with each new closed bar + structure."""

    def __init__(self, *, tp1_fraction: float = 0.4, tp2_fraction: float = 0.3) -> None:
        self.tp1_fraction = tp1_fraction
        self.tp2_fraction = tp2_fraction

    def on_bar(
        self, pos: ManagedPosition, bar: Bar, structure: StructureView
    ) -> ManageDecision:
        intent = pos.intent
        side = pos.side
        decision = ManageDecision()

        # excursions
        if side is Side.LONG:
            pos.mfe = max(pos.mfe, bar.high - pos.entry_px)
            pos.mae = min(pos.mae, bar.low - pos.entry_px)
        else:
            pos.mfe = max(pos.mfe, pos.entry_px - bar.low)
            pos.mae = min(pos.mae, pos.entry_px - bar.high)

        # 1) stop hit?
        if self._stop_hit(pos, bar):
            decision.exit_all = True
            decision.exit_reason = (
                ExitReason.BREAKEVEN if pos.breakeven_done and abs(pos.stop_px - pos.entry_px) < 1e-9
                else (ExitReason.TRAIL if pos.breakeven_done else ExitReason.STOP)
            )
            return decision

        # 2) runner target (ERL) hit -> exit remainder
        if self._reached(side, bar, intent.runner_target_px):
            decision.exit_all = True
            decision.exit_reason = ExitReason.RUNNER_TARGET
            return decision

        # 3) partials at interim liquidity
        if not pos.tp1_taken and self._reached(side, bar, intent.tp1_px):
            qty = max(1, int(round(pos.qty * self.tp1_fraction)))
            qty = min(qty, pos.qty_remaining - 1) if pos.qty_remaining > 1 else 0
            if qty > 0:
                pos.tp1_taken = True
                decision.take_partial_qty = qty
                decision.note = "tp1"
                return decision
            pos.tp1_taken = True
        if pos.tp1_taken and not pos.tp2_taken and self._reached(side, bar, intent.tp2_px):
            qty = max(1, int(round(pos.qty * self.tp2_fraction)))
            qty = min(qty, pos.qty_remaining - 1) if pos.qty_remaining > 1 else 0
            if qty > 0:
                pos.tp2_taken = True
                decision.take_partial_qty = qty
                decision.note = "tp2"
                return decision
            pos.tp2_taken = True

        # 4) breakeven / trail — ONLY after structural break or displacement
        if not pos.breakeven_done and (structure.bos or structure.displacement):
            pos.breakeven_done = True
            pos.be_trigger = (
                BreakevenTrigger.STRUCTURAL_BREAK if structure.bos
                else BreakevenTrigger.DISPLACEMENT
            )
            decision.new_stop = pos.entry_px
            decision.note = f"breakeven ({pos.be_trigger.value})"
            return decision

        # 5) trail behind structure once we're past breakeven
        if pos.breakeven_done and structure.trail_to is not None:
            improves = (
                (side is Side.LONG and structure.trail_to > pos.stop_px)
                or (side is Side.SHORT and structure.trail_to < pos.stop_px)
            )
            if improves:
                decision.new_stop = structure.trail_to
                decision.note = "trail"
        return decision

    @staticmethod
    def _stop_hit(pos: ManagedPosition, bar: Bar) -> bool:
        if pos.side is Side.LONG:
            return bar.low <= pos.stop_px
        return bar.high >= pos.stop_px

    @staticmethod
    def _reached(side: Side, bar: Bar, level: float | None) -> bool:
        if level is None:
            return False
        if side is Side.LONG:
            return bar.high >= level
        return bar.low <= level

    @staticmethod
    def record(pos: ManagedPosition, ts: datetime, event: str, to_px: float | None,
               note: str = "") -> None:
        pos.events.append(ManagementEvent(ts=ts, event=event, from_px=pos.stop_px,
                                          to_px=to_px, note=note))
