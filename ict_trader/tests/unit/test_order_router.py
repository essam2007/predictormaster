from __future__ import annotations

from datetime import datetime

from ict_trader.clock import ET
from ict_trader.domain.enums import Side
from ict_trader.domain.signals import EntryIntent, SetupSnapshot
from ict_trader.execution.order_router import (
    build_bracket,
    idempotency_key,
    split_quantity,
)


def _intent(side=Side.LONG):
    snap = SetupSnapshot(ts=datetime(2024, 5, 15, 10, 0, tzinfo=ET), bias=side)
    return EntryIntent(ts=snap.ts, side=side, entry_px=100.07, stop_px=98.03,
                       tp1_px=104.1, tp2_px=107.2, runner_target_px=110, risk_r=5, setup=snap)


def test_split_quantity_keeps_runner():
    assert split_quantity(1, (0.4, 0.3)) == (0, 0, 1)
    assert split_quantity(2, (0.4, 0.3)) == (1, 0, 1)
    q1, q2, runner = split_quantity(5, (0.4, 0.3))
    assert q1 + q2 + runner == 5 and runner >= 1


def test_build_bracket_rounds_to_tick_and_has_legs():
    spec = build_bracket(_intent(), qty=3, symbol="NQ", tick_size=0.25)
    legs = {leg.leg: leg for leg in spec.legs}
    assert "entry" in legs and "runner_stop" in legs
    # entry rounded to nearest 0.25
    assert legs["entry"].price == 100.0
    # long entry is a Buy, exits are Sell
    assert legs["entry"].action == "Buy"
    assert all(leg.action == "Sell" for leg in spec.legs if leg.leg != "entry")
    # protective stops across tranches sum to the entry quantity (no overlap)
    stop_qty = sum(leg.qty for leg in spec.legs if leg.leg.endswith("_stop"))
    assert stop_qty == 3
    # all protective stops rounded to the same tick
    assert all(leg.stop_price == 98.0 for leg in spec.legs if leg.leg.endswith("_stop"))
    # the runner tranche is trailed (no fixed TP) toward the ERL
    assert legs["runner_stop"].order_type.value == "trailing_stop"


def test_idempotency_key_stable_and_distinct():
    intent = _intent()
    assert idempotency_key(intent, "entry") == idempotency_key(intent, "entry")
    assert idempotency_key(intent, "entry") != idempotency_key(intent, "stop")
