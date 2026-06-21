from __future__ import annotations

from datetime import datetime

from ict_trader.clock import ET
from ict_trader.confluence.aggregator import ConfluenceAggregator
from ict_trader.domain.enums import ComponentId, Side
from ict_trader.domain.signals import ComponentState


def _full_states(bias=Side.LONG) -> dict[ComponentId, ComponentState]:
    states: dict[ComponentId, ComponentState] = {}
    for cid in ComponentId:
        if cid is ComponentId.STRUCTURE:
            continue
        states[cid] = ComponentState(cid, present=True, bias=bias, confidence=1.0)
    states[ComponentId.TIMING].payload = {"killzone": "silver_bullet", "quarter_idx": 2,
                                          "amd": "distribution"}
    states[ComponentId.LTF_TRIGGER].payload = {"entry": 100.0, "stop": 98.0}
    return states


def test_full_nine_stack_passes_and_builds_intent():
    agg = ConfluenceAggregator()
    ts = datetime(2024, 5, 15, 10, 0, tzinfo=ET)
    snap, intent = agg.evaluate(ts, Side.LONG, _full_states(),
                                erl_target=110.0, daily_extreme_in=False)
    assert snap.stack_count == 9
    assert snap.gated_pass is True
    assert intent is not None
    assert intent.entry_px == 100.0 and intent.stop_px == 98.0
    assert intent.runner_target_px == 110.0
    assert intent.risk_r > 0  # (target-entry)/(entry-stop) = 10/2 = 5
    assert snap.killzone.value == "silver_bullet" and snap.quarter_idx == 2


def test_missing_one_component_does_not_pass():
    agg = ConfluenceAggregator()
    states = _full_states()
    states[ComponentId.SMT2] = ComponentState(ComponentId.SMT2, present=False, bias=Side.LONG)
    snap, intent = agg.evaluate(datetime(2024, 5, 15, 10, 0, tzinfo=ET), Side.LONG, states,
                                erl_target=110.0, daily_extreme_in=False)
    assert snap.stack_count == 8
    assert snap.gated_pass is False
    assert intent is None


def test_degraded_feed_blocks_pass():
    agg = ConfluenceAggregator()
    states = _full_states()
    states[ComponentId.PSP].payload = {"degraded": True}
    snap, intent = agg.evaluate(datetime(2024, 5, 15, 10, 0, tzinfo=ET), Side.LONG, states,
                                erl_target=110.0, daily_extreme_in=False)
    assert snap.gated_pass is False and intent is None
