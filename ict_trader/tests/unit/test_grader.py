from __future__ import annotations

from ict_trader.llm.grader import _parse_grade_json, grade_available, grade_trade


def test_no_op_without_api_key(monkeypatch):
    """Without ANTHROPIC_API_KEY the grader is a clean no-op (the default deployment)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert grade_available() is False
    result = grade_trade(
        side="long", realized_r=2.0, elements=[{"name": "HTF FVG delivery", "present": True}],
        summary="LONG setup", killzone="ny_am", moved_to_be_early=False,
    )
    assert result is None


def test_parse_grade_json_handles_bare_and_wrapped():
    assert _parse_grade_json('{"grade": "A", "rationale": "clean"}') == {"grade": "A", "rationale": "clean"}
    # tolerates prose around the JSON object
    wrapped = 'Here is my grade:\n{"grade": "C", "rationale": "be early"}\nThanks!'
    assert _parse_grade_json(wrapped) == {"grade": "C", "rationale": "be early"}
    # non-JSON returns None rather than raising
    assert _parse_grade_json("no json here") is None
    # a JSON array (not an object) is rejected
    assert _parse_grade_json("[1, 2, 3]") is None
