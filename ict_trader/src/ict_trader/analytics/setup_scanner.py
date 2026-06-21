"""Scan aligned ES/NQ bars for candidate ICT reversal setups and grade them.

First-pass surface-and-rank for the Setup Review queue (see TODO.md): at each killzone bar it
checks for an IFVG/LTF entry trigger (both directions), grades the window with
``trade_analyzer`` (FVG / IFVG / structure / killzone / path), checks real ES↔NQ **SMT**
divergence as a bonus pillar, derives a drawn-liquidity target, and returns ranked candidates.

Pure (no I/O, no plotting) so it's testable; the CLI/rendering lives in ``scripts/scan_setups.py``.
Honest scope: the detectors are simplified (5m FVGs stand in for true 1h/4h HTF delivery; no
nested two-stage SMT yet) — these are *candidates to rate*, not gospel grades.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..detectors.ifvg import LTFTriggerDetector
from ..detectors.smt import detect_smt
from ..domain.bars import Bar
from ..domain.enums import Killzone, Side, Timeframe
from .trade_analyzer import analyze_trade

_KILLZONES = (Killzone.NY_AM, Killzone.SILVER_BULLET)


def killzone_et(ts: datetime) -> Killzone:
    """Classify a bar by its (ET-localized) open time. SB (10–11) ⊂ NY-AM (09:30–12:00)."""
    hm = ts.hour * 60 + ts.minute
    if 600 <= hm < 660:
        return Killzone.SILVER_BULLET
    if 570 <= hm < 720:
        return Killzone.NY_AM
    return Killzone.NONE


@dataclass(slots=True)
class SetupCandidate:
    ts: datetime
    bar_index: int
    side: Side
    killzone: Killzone
    grade: str
    score: float
    entry: float
    stop: float
    target: float
    rr: float
    ifvg_lower: float
    ifvg_upper: float
    smt: bool
    smt_detail: str
    summary: str


def scan(
    nq: list[Bar], es: list[Bar], *,
    window: int = 140, smt_lookback: int = 40, draw_lookback: int = 48, min_rr: float = 1.0,
) -> list[SetupCandidate]:
    """Return ranked candidate setups from time-aligned NQ/ES bars (ET-localized ts_open)."""
    if len(nq) != len(es):
        raise ValueError("nq and es must be time-aligned (equal length)")
    trig = LTFTriggerDetector()
    out: list[SetupCandidate] = []
    seen: set[tuple] = set()
    for i in range(20, len(nq)):
        kz = killzone_et(nq[i].ts_open)
        if kz not in _KILLZONES:
            continue
        nq_win = nq[max(0, i - window + 1): i + 1]
        for side in (Side.LONG, Side.SHORT):
            st = trig.update(nq_win, Timeframe.M5, side)
            entry, stop = st.payload.get("entry"), st.payload.get("stop")
            ifl, ifu = st.payload.get("ifvg_lower"), st.payload.get("ifvg_upper")
            if not st.present or entry is None or stop is None or ifl is None or ifu is None:
                continue
            key = (side, round(ifl, 1), round(ifu, 1))
            if key in seen:  # only log the first bar a given IFVG triggers
                continue
            seen.add(key)
            draw = nq[max(0, i - draw_lookback): i + 1]
            if side is Side.LONG:
                target = max(b.high for b in draw)
                target = target if target > entry else entry + abs(entry - stop) * 2
            else:
                target = min(b.low for b in draw)
                target = target if target < entry else entry - abs(stop - entry) * 2
            risk = abs(entry - stop) or 0.25
            rr = round(abs(target - entry) / risk, 2)
            if rr < min_rr:
                continue
            div = detect_smt(es[max(0, i - smt_lookback): i + 1],
                             nq[max(0, i - smt_lookback): i + 1], side)
            smt_detail = (f"{div['sweeper']} swept / {div['holder']} held @ {div['level']:.2f}"
                          if div else "—")
            ana = analyze_trade(side=side, entry_ts=nq[i].ts_open, bars=nq_win,
                                killzone=kz, path_clean=True)
            out.append(SetupCandidate(
                ts=nq[i].ts_open, bar_index=i, side=side, killzone=kz, grade=ana.grade,
                score=ana.score, entry=float(entry), stop=float(stop), target=float(target),
                rr=rr, ifvg_lower=float(ifl), ifvg_upper=float(ifu), smt=div is not None,
                smt_detail=smt_detail, summary=ana.summary))
    # rank: SMT present first, then deterministic score, then R:R
    out.sort(key=lambda c: (c.smt, c.score, c.rr), reverse=True)
    return out
