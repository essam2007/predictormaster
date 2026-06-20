"""Weighted confluence scoring.

We *trade* only the full all-9 stack, but we *score and log* every candidate so the
research deck can later reveal which components actually carry edge (and whether fewer
components still hold). Weights are configurable via ``strategy.yaml``.
"""

from __future__ import annotations

from ..domain.enums import ComponentId
from ..domain.signals import ComponentState

DEFAULT_WEIGHTS: dict[ComponentId, float] = {
    ComponentId.FVG: 0.15,
    ComponentId.SMT1: 0.15,
    ComponentId.SMT2: 0.10,
    ComponentId.PSP: 0.12,
    ComponentId.LTF_TRIGGER: 0.18,
    ComponentId.LRLR: 0.12,
    ComponentId.TIMING: 0.10,
    ComponentId.DAYFILTER: 0.05,
    ComponentId.MANAGEMENT: 0.03,
}


def weighted_score(
    states: dict[ComponentId, ComponentState],
    weights: dict[ComponentId, float] | None = None,
) -> float:
    """Confidence-weighted score in [0, 1]."""
    w = weights or DEFAULT_WEIGHTS
    total = sum(w.values())
    if total <= 0:
        return 0.0
    acc = 0.0
    for cid, weight in w.items():
        st = states.get(cid)
        if st and st.present:
            acc += weight * max(0.0, min(1.0, st.confidence or 1.0))
    return round(acc / total, 4)
