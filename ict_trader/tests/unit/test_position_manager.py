from __future__ import annotations

from tests.conftest import mk_bar

from ict_trader.detectors.structure import StructureView
from ict_trader.domain.enums import BreakevenTrigger, Side
from ict_trader.domain.signals import EntryIntent, SetupSnapshot
from ict_trader.execution.position_manager import ManagedPosition, PositionManager


def _intent(side=Side.LONG):
    snap = SetupSnapshot(ts=mk_bar(0, 0, 0, 0, 0).ts_open, bias=side)
    return EntryIntent(ts=snap.ts, side=side, entry_px=100, stop_px=98, tp1_px=104,
                       tp2_px=107, runner_target_px=110, risk_r=5, setup=snap)


def _pos(side=Side.LONG, qty=3):
    intent = _intent(side)
    return ManagedPosition(intent=intent, qty=qty, entry_px=100, stop_px=98, side=side)


def _flat_structure():
    return StructureView(last_swing_high=None, last_swing_low=99, bos=False,
                         displacement=False, trail_to=99)


def test_no_breakeven_on_pullback():
    """The headline fix: a normal pullback must NOT move the stop to breakeven."""
    pm = PositionManager()
    pos = _pos()
    bar = mk_bar(1, 100.5, 101, 99.5, 100.2)  # small pullback, no new structure
    decision = pm.on_bar(pos, bar, _flat_structure())
    assert decision.new_stop is None
    assert pos.breakeven_done is False
    assert pos.moved_to_be_early is False


def test_breakeven_only_after_structural_break():
    pm = PositionManager()
    pos = _pos()
    bar = mk_bar(1, 100.5, 102, 100.2, 101.8)  # advancing, below tp1
    struct = StructureView(last_swing_high=101, last_swing_low=100, bos=True,
                           displacement=False, trail_to=100)
    decision = pm.on_bar(pos, bar, struct)
    assert decision.new_stop == pos.entry_px
    assert pos.breakeven_done is True
    assert pos.be_trigger is BreakevenTrigger.STRUCTURAL_BREAK
    assert pos.moved_to_be_early is False  # never the flawed trigger


def test_partial_taken_at_tp1():
    pm = PositionManager()
    pos = _pos(qty=3)
    bar = mk_bar(1, 103, 104.5, 102, 104.2)  # high >= tp1 104
    decision = pm.on_bar(pos, bar, _flat_structure())
    assert decision.take_partial_qty >= 1
    assert pos.tp1_taken is True


def test_runner_target_exit():
    pm = PositionManager()
    pos = _pos(qty=1)
    bar = mk_bar(1, 108, 110.5, 107, 110.2)  # reaches ERL 110
    decision = pm.on_bar(pos, bar, _flat_structure())
    assert decision.exit_all is True
    assert decision.exit_reason.value == "runner_target"


def test_stop_hit_exit():
    pm = PositionManager()
    pos = _pos(qty=1)
    bar = mk_bar(1, 99, 99.5, 97.5, 98.0)  # low <= stop 98
    decision = pm.on_bar(pos, bar, _flat_structure())
    assert decision.exit_all is True
    assert decision.exit_reason.value == "stop"
