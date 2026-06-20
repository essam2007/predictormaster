"""The confluence aggregator: component states -> setup snapshot (-> entry intent).

Decision model:
  * Hard gates (must all hold to TRADE): TIMING ok (killzone, no news, extreme-not-in),
    DAYFILTER ok, and no degraded cross-instrument feed.
  * A+ structural stack: all nine components present.
  * Always produce a SetupSnapshot (even non-passing) for calibration; only emit an
    EntryIntent when ``gated_pass`` is True.
"""

from __future__ import annotations

from datetime import datetime

from ..domain.enums import AMDPhase, ComponentId, Killzone, Side
from ..domain.signals import ComponentState, EntryIntent, SetupSnapshot
from .scoring import DEFAULT_WEIGHTS, weighted_score


class ConfluenceAggregator:
    def __init__(
        self,
        *,
        weights: dict[ComponentId, float] | None = None,
        require_all: bool = True,
        tp1_fraction: float = 0.4,
        tp2_fraction: float = 0.7,
    ) -> None:
        self.weights = weights or DEFAULT_WEIGHTS
        self.require_all = require_all
        self.tp1_fraction = tp1_fraction
        self.tp2_fraction = tp2_fraction

    def evaluate(
        self,
        ts: datetime,
        bias: Side,
        states: dict[ComponentId, ComponentState],
        *,
        erl_target: float | None,
        daily_extreme_in: bool,
    ) -> tuple[SetupSnapshot, EntryIntent | None]:
        def ok(cid: ComponentId) -> bool:
            st = states.get(cid)
            return bool(st and st.present)

        timing = states.get(ComponentId.TIMING)
        snap = SetupSnapshot(
            ts=ts,
            bias=bias,
            fvg_ok=ok(ComponentId.FVG),
            smt1_ok=ok(ComponentId.SMT1),
            smt2_ok=ok(ComponentId.SMT2),
            psp_ok=ok(ComponentId.PSP),
            ltf_trigger_ok=ok(ComponentId.LTF_TRIGGER),
            lrlr_ok=ok(ComponentId.LRLR),
            timing_ok=ok(ComponentId.TIMING),
            dayfilter_ok=ok(ComponentId.DAYFILTER),
            management_ok=True,  # a valid management plan always exists in this engine
            daily_extreme_in=daily_extreme_in,
            path_clean=ok(ComponentId.LRLR),
            killzone=Killzone(timing.payload.get("killzone", "none")) if timing else Killzone.NONE,
            quarter_idx=int(timing.payload.get("quarter_idx", -1)) if timing else -1,
            amd_phase=AMDPhase(states[ComponentId.TIMING].payload.get("amd", AMDPhase.UNKNOWN.value))
            if timing and "amd" in timing.payload else AMDPhase.UNKNOWN,
            components={cid.value: _state_to_dict(st) for cid, st in states.items()},
        )
        snap.score = weighted_score(states, self.weights)

        # hard gates
        gates_ok = snap.timing_ok and snap.dayfilter_ok and not _any_degraded(states)
        structural_ok = (snap.stack_count == 9) if self.require_all else (snap.score >= 0.7)
        snap.gated_pass = bool(gates_ok and structural_ok)

        intent = None
        ltf = states.get(ComponentId.LTF_TRIGGER)
        if snap.gated_pass and ltf and ltf.present and erl_target is not None:
            entry = float(ltf.payload["entry"])
            stop = float(ltf.payload["stop"])
            intent = self._build_intent(ts, bias, entry, stop, erl_target, snap)
            snap.entry_px = entry
            snap.stop_px = stop
            snap.tp1_px = intent.tp1_px
            snap.tp2_px = intent.tp2_px
            snap.runner_target_px = intent.runner_target_px
            snap.planned_risk_r = intent.risk_r
        return snap, intent

    def _build_intent(self, ts, bias, entry, stop, erl_target, snap) -> EntryIntent:
        risk = abs(entry - stop)
        total = abs(erl_target - entry)
        if bias is Side.LONG:
            tp1 = entry + self.tp1_fraction * total
            tp2 = entry + self.tp2_fraction * total
        else:
            tp1 = entry - self.tp1_fraction * total
            tp2 = entry - self.tp2_fraction * total
        risk_r = (total / risk) if risk > 0 else 0.0
        return EntryIntent(
            ts=ts, side=bias, entry_px=entry, stop_px=stop, tp1_px=tp1, tp2_px=tp2,
            runner_target_px=erl_target, risk_r=round(risk_r, 2), setup=snap,
            reason=f"A+ stack ({snap.stack_count}/9), score={snap.score}",
        )


def _state_to_dict(st: ComponentState) -> dict:
    return {"present": st.present, "confidence": st.confidence, "payload": st.payload}


def _any_degraded(states: dict[ComponentId, ComponentState]) -> bool:
    return any(s.payload.get("degraded") for s in states.values())
