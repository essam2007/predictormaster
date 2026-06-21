"""Optional Claude narrative grade for a logged trade (Phase E).

Layers a short letter grade + rationale on top of the deterministic detector analysis
(``analytics/trade_analyzer``). It grades the *setup quality and process discipline* — not
whether the trade happened to win — and explicitly penalizes the documented edge leak
(moving to breakeven on the first pullback).

Lazy + optional by design: the ``anthropic`` SDK is imported only when called, and the whole
thing no-ops (returns ``None``) when ``ANTHROPIC_API_KEY`` is unset or the SDK isn't installed
— so the deck runs perfectly without an API key, and CI needs no extra dependency.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

# Cost-efficient default for high-volume per-trade grading; override with ICT_TRADER_GRADER_MODEL.
_DEFAULT_MODEL = "claude-sonnet-4-6"
_PROMPT = """\
You are a senior ICT (Inner Circle Trader) desk reviewer grading ONE futures trade on SETUP
QUALITY and PROCESS DISCIPLINE — NOT on whether it won or lost. The model's edge comes from:
HTF FVG delivery, an IFVG / LTF trigger, a market-structure shift, killzone timing, a clean
low-resistance path, and — most importantly — HOLDING THE RUNNER. Moving to breakeven on the
first pullback is the documented leak that caps the runner the whole model depends on, so
penalize it even when the trade still won.

Trade: side={side}, realized={realized_r}R, killzone={killzone}, moved_to_breakeven_early={be}.
Detected elements PRESENT: {present}
Detected elements ABSENT: {absent}
Deterministic summary: {summary}

Return ONLY a JSON object, no prose around it:
{{"grade": "A|B|C|D|F", "rationale": "<= 2 sentences on setup quality and discipline"}}"""


@dataclass(slots=True)
class LLMGrade:
    grade: str
    rationale: str
    model: str


def grade_available() -> bool:
    """True only if a key is configured — the cheap check the request path gates on."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _parse_grade_json(text: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            obj = json.loads(match.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


def grade_trade(
    *, side: str, realized_r: float, elements: list[dict[str, Any]], summary: str,
    killzone: str, moved_to_be_early: bool,
) -> LLMGrade | None:
    """Call Claude for a narrative grade. Returns None on any failure (advisory only)."""
    if not grade_available():
        return None
    try:
        import anthropic
    except ImportError:
        return None

    model = os.environ.get("ICT_TRADER_GRADER_MODEL", _DEFAULT_MODEL)
    present = ", ".join(e["name"] for e in elements if e.get("present")) or "none"
    absent = ", ".join(e["name"] for e in elements if not e.get("present")) or "none"
    prompt = _PROMPT.format(
        side=side, realized_r=realized_r, killzone=killzone, be=moved_to_be_early,
        present=present, absent=absent, summary=summary,
    )
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model, max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            getattr(b, "text", "") for b in msg.content if getattr(b, "type", None) == "text"
        )
        data = _parse_grade_json(text)
        if data is None:
            return None
        grade = (str(data.get("grade", "")).strip().upper()[:1]) or "C"
        rationale = str(data.get("rationale", "")).strip()[:1000]
        return LLMGrade(grade=grade, rationale=rationale, model=model)
    except Exception:  # noqa: BLE001 - grading is advisory; never raise into the request path
        return None
