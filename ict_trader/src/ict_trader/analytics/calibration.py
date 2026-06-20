"""Component calibration: does a component's presence / the weighted score predict R?

Answers the research's core question — *which confluences actually carry the edge?* — by
correlating each component (and the overall score) with realized outcomes.
"""

from __future__ import annotations

from ..domain.signals import SetupSnapshot
from ..domain.trades import Trade

_COMPONENT_FLAGS = (
    "fvg_ok", "smt1_ok", "smt2_ok", "psp_ok", "ltf_trigger_ok",
    "lrlr_ok", "timing_ok", "dayfilter_ok",
)


def component_lift(trades: list[Trade], setups: list[SetupSnapshot]) -> dict:
    """For each component, compare avg-R when the matched setup had it present vs absent.

    Matches a trade to its setup by entry timestamp == setup timestamp.
    """
    by_ts = {s.ts: s for s in setups}
    rows: dict[str, dict] = {}
    for flag in _COMPONENT_FLAGS:
        present_r: list[float] = []
        absent_r: list[float] = []
        for t in trades:
            if t.is_open:
                continue
            s = by_ts.get(t.entry_ts)
            if s is None:
                continue
            (present_r if getattr(s, flag) else absent_r).append(t.realized_r)
        rows[flag] = {
            "n_present": len(present_r),
            "avg_r_present": round(sum(present_r) / len(present_r), 3) if present_r else None,
            "n_absent": len(absent_r),
            "avg_r_absent": round(sum(absent_r) / len(absent_r), 3) if absent_r else None,
        }
    return rows


def score_reliability(trades: list[Trade], bins: int = 5) -> list[dict]:
    """Bucket trades by setup score and report avg-R per bin (does score track R?)."""
    closed = [t for t in trades if not t.is_open]
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        grp = [t for t in closed if lo <= t.setup_score < hi or (b == bins - 1 and t.setup_score == 1.0)]
        if grp:
            out.append({
                "score_range": f"{lo:.1f}-{hi:.1f}",
                "n": len(grp),
                "avg_r": round(sum(t.realized_r for t in grp) / len(grp), 3),
            })
    return out
