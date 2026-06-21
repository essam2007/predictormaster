"""Auto-detect the ICT setup elements present in a logged trade's bar window.

Given a trade (side + entry time + tags) and the OHLC bars around its entry, run the pure
single-instrument detectors (HTF FVG delivery, IFVG/LTF trigger, market structure) over the
window up to entry, combine with the trade's own recorded timing/path tags, and produce:

- a list of detected ``elements`` (which conditions were present, with detail + weight),
- a deterministic 0..1 ``score`` and a letter grade,
- a short human-readable ``summary``.

This is the deterministic half of the grader; an optional Claude narrative grade (Phase E)
layers on top. Pure function of bars + trade tags — no I/O — so it is fully testable and runs
identically online and in backtest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from ..detectors import structure as structure_mod
from ..detectors.fvg import FVGDetector
from ..detectors.ifvg import LTFTriggerDetector
from ..domain.bars import Bar
from ..domain.enums import Killzone, Side, Timeframe

# Element weights sum to 1.0 so the score is a clean 0..1 fraction.
_GOOD_KILLZONES = {Killzone.NY_AM, Killzone.SILVER_BULLET}


@dataclass(slots=True)
class DetectedElement:
    name: str
    present: bool
    weight: float
    detail: str = ""


@dataclass(slots=True)
class TradeAnalysis:
    score: float
    grade: str
    summary: str
    elements: list[DetectedElement] = field(default_factory=list)
    model: str = "detectors-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score, "grade": self.grade, "summary": self.summary,
            "model": self.model, "elements": [asdict(e) for e in self.elements],
        }


def _as_side(v: Side | str) -> Side:
    if isinstance(v, Side):
        return v
    try:
        return Side(str(v).lower())
    except ValueError:
        return Side.NONE


def _as_killzone(v: Killzone | str) -> Killzone:
    if isinstance(v, Killzone):
        return v
    try:
        return Killzone(str(v).lower())
    except ValueError:
        return Killzone.NONE


def _grade(score: float) -> str:
    return "A" if score >= 0.8 else "B" if score >= 0.6 else "C" if score >= 0.4 else "D"


def analyze_trade(
    *,
    side: Side | str,
    entry_ts: datetime,
    bars: list[Bar],
    killzone: Killzone | str = Killzone.NONE,
    path_clean: bool = True,
    moved_to_be_early: bool = False,
    timeframe: Timeframe = Timeframe.M5,
) -> TradeAnalysis:
    """Detect & grade the ICT elements behind a trade from its pre-entry bar window."""
    s = _as_side(side)
    kz = _as_killzone(killzone)
    window = [b for b in bars if b.is_closed and b.ts_open <= entry_ts]

    elements: list[DetectedElement] = []
    if len(window) >= 4 and s is not Side.NONE:
        fvg = FVGDetector().update(window, timeframe, s)
        ltf = LTFTriggerDetector().update(window, timeframe, s)
        view = structure_mod.analyze(window, s)
        elements.append(DetectedElement(
            "HTF FVG delivery", fvg.present, 0.25,
            _fmt_zone(fvg.payload) if fvg.present else ""))
        elements.append(DetectedElement(
            "IFVG / LTF trigger", ltf.present, 0.25,
            _fmt_zone(ltf.payload) if ltf.present else ""))
        elements.append(DetectedElement("Structure shift (BOS)", view.bos, 0.15))
        elements.append(DetectedElement("Displacement leg", view.displacement, 0.10))
    else:
        for name, w in (("HTF FVG delivery", 0.25), ("IFVG / LTF trigger", 0.25),
                        ("Structure shift (BOS)", 0.15), ("Displacement leg", 0.10)):
            elements.append(DetectedElement(name, False, w, "insufficient bars in window"))

    elements.append(DetectedElement("Killzone timing", kz in _GOOD_KILLZONES, 0.15, kz.value))
    elements.append(DetectedElement("Clean path (LRLR)", bool(path_clean), 0.10))

    score = round(sum(e.weight for e in elements if e.present), 3)
    grade = _grade(score)
    present = [e.name for e in elements if e.present]
    summary = (
        f"{s.value.upper()} setup — {len(present)}/{len(elements)} elements present"
        f" ({', '.join(present) if present else 'none detected'}). "
        f"Deterministic score {score}/1.0 (grade {grade})."
    )
    if moved_to_be_early:
        summary += (" ⚠ Moved to breakeven early — this likely capped the runner the model "
                    "depends on (the documented edge leak).")
    return TradeAnalysis(score=score, grade=grade, summary=summary, elements=elements)


def _fmt_zone(payload: dict[str, Any]) -> str:
    lo, up = payload.get("lower"), payload.get("upper")
    if lo is None or up is None:
        return ""
    return f"{lo:.2f}–{up:.2f}"
