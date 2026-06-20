"""Low-Resistance Liquidity Run (LRLR): is the path to the ERL target clean?

Scan the price interval between entry and the target (the day high/low). If any *opposing*
PD-array (FVG/OB/breaker) sits in that lane, the run is high-resistance and the setup is
downgraded. Clean only if the lane is empty.
"""

from __future__ import annotations

from ..domain.enums import ComponentId, Side
from ..domain.pdarrays import FVG
from ..domain.signals import ComponentState


def obstacles_in_path(
    entry: float, target: float, side: Side, arrays: list[FVG]
) -> list[FVG]:
    """Opposing, unfilled arrays whose zone overlaps the (entry, target) lane."""
    lo, hi = (entry, target) if entry <= target else (target, entry)
    opp = side.opposite
    out: list[FVG] = []
    for f in arrays:
        if f.filled or f.side is not opp:
            continue
        # overlap between [f.lower, f.upper] and [lo, hi]
        if f.upper >= lo and f.lower <= hi:
            out.append(f)
    return out


class LRLRDetector:
    component = ComponentId.LRLR

    def update(
        self, entry: float, target: float, side: Side, arrays: list[FVG]
    ) -> ComponentState:
        if side is Side.NONE or target is None:
            return ComponentState(self.component, present=False, bias=side)
        obstacles = obstacles_in_path(entry, target, side, arrays)
        clean = len(obstacles) == 0
        return ComponentState(
            self.component, present=clean, bias=side,
            confidence=1.0 if clean else 0.0,
            payload={"path_clean": clean, "n_obstacles": len(obstacles),
                     "obstacles": [{"lower": o.lower, "upper": o.upper} for o in obstacles]},
        )
