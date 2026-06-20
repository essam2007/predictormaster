"""ES/NQ Smart-Money-Technique (SMT) divergence — Stage-1 and nested Stage-2.

At a recognized liquidity level one index *sweeps* (makes a new extreme beyond the level)
while the other *holds* (fails to confirm). The holder is the truth-teller. We never decide
divergence on a degraded (unsynced) co-bar.
"""

from __future__ import annotations

from ..domain.bars import Bar
from ..domain.enums import ComponentId, Side
from ..domain.signals import ComponentState
from .base import swing_points


def _last_swing_low(bars: list[Bar], strength: int) -> int | None:
    _, lows = swing_points(bars, strength)
    return lows[-1] if lows else None


def _last_swing_high(bars: list[Bar], strength: int) -> int | None:
    highs, _ = swing_points(bars, strength)
    return highs[-1] if highs else None


def detect_smt(
    es: list[Bar],
    nq: list[Bar],
    side: Side,
    *,
    strength: int = 2,
) -> dict | None:
    """Detect a divergence in ``side`` direction across aligned ES/NQ closed bars.

    Returns a dict describing the divergence (sweeper/holder/level) or ``None``.
    ``es`` and ``nq`` MUST be time-aligned (same length, same timestamps).
    """
    if len(es) != len(nq) or len(es) < 2 * strength + 2 or side is Side.NONE:
        return None

    if side is Side.LONG:
        es_piv = _last_swing_low(es, strength)
        nq_piv = _last_swing_low(nq, strength)
        if es_piv is None or nq_piv is None:
            return None
        ref = min(es_piv, nq_piv)
        if ref >= len(es) - 1:
            return None
        es_level, nq_level = es[es_piv].low, nq[nq_piv].low
        es_ext = min(b.low for b in es[ref + 1 :])
        nq_ext = min(b.low for b in nq[ref + 1 :])
        es_swept = es_ext < es_level
        nq_swept = nq_ext < nq_level
        if es_swept == nq_swept:  # both or neither -> no divergence
            return None
        sweeper = "ES" if es_swept else "NQ"
        holder = "NQ" if es_swept else "ES"
        level = es_level if es_swept else nq_level
    else:  # SHORT
        es_piv = _last_swing_high(es, strength)
        nq_piv = _last_swing_high(nq, strength)
        if es_piv is None or nq_piv is None:
            return None
        ref = min(es_piv, nq_piv)
        if ref >= len(es) - 1:
            return None
        es_level, nq_level = es[es_piv].high, nq[nq_piv].high
        es_ext = max(b.high for b in es[ref + 1 :])
        nq_ext = max(b.high for b in nq[ref + 1 :])
        es_swept = es_ext > es_level
        nq_swept = nq_ext > nq_level
        if es_swept == nq_swept:
            return None
        sweeper = "ES" if es_swept else "NQ"
        holder = "NQ" if es_swept else "ES"
        level = es_level if es_swept else nq_level

    return {"sweeper": sweeper, "holder": holder, "level": level, "side": side.value}


class SMTDetector:
    """Stage-1 (HTF) and Stage-2 (nested) SMT share this logic; the engine supplies the
    appropriate aligned series (e.g. 15m/1h for stage-1, 90m-quarter slice for stage-2)."""

    def __init__(self, stage: int, *, strength: int = 2) -> None:
        self.stage = stage
        self.component = ComponentId.SMT1 if stage == 1 else ComponentId.SMT2
        self.strength = strength

    def update(self, es: list[Bar], nq: list[Bar], side: Side) -> ComponentState:
        es_c = [b for b in es if b.is_closed]
        nq_c = [b for b in nq if b.is_closed]
        if len(es_c) != len(nq_c):  # degraded / unsynced -> refuse
            return ComponentState(self.component, present=False, bias=side,
                                  payload={"degraded": True})
        div = detect_smt(es_c, nq_c, side, strength=self.strength)
        if div is None:
            ts = es_c[-1].ts_open if es_c else None
            return ComponentState(self.component, present=False, bias=side, ts=ts)
        return ComponentState(
            self.component, present=True, bias=side, confidence=0.75,
            ts=es_c[-1].ts_open,
            payload={"stage": self.stage, **div},
        )
