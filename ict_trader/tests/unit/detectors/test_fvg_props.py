from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings
from tests.conftest import series_from

from ict_trader.detectors.fvg import detect_fvgs, resolve_fills
from ict_trader.domain.enums import Side, Timeframe


@st.composite
def _ohlc(draw):
    o = draw(st.floats(50, 150, allow_nan=False, allow_infinity=False))
    c = draw(st.floats(50, 150, allow_nan=False, allow_infinity=False))
    up = draw(st.floats(0, 5, allow_nan=False, allow_infinity=False))
    dn = draw(st.floats(0, 5, allow_nan=False, allow_infinity=False))
    return (round(o, 2), round(max(o, c) + up, 2), round(min(o, c) - dn, 2), round(c, 2))


@settings(max_examples=60, deadline=None)
@given(st.lists(_ohlc(), min_size=3, max_size=40))
def test_detected_fvgs_have_valid_bounds(rows):
    bars = series_from(rows)
    for f in detect_fvgs(bars, Timeframe.M5, tick_size=0.25, min_ticks=1.0):
        assert f.lower < f.upper                       # well-formed gap
        assert (f.upper - f.lower) >= 0.25 - 1e-9      # respects min size
        assert f.side in (Side.LONG, Side.SHORT)


@settings(max_examples=60, deadline=None)
@given(st.lists(_ohlc(), min_size=3, max_size=40))
def test_resolve_fills_is_idempotent(rows):
    bars = series_from(rows)
    fvgs = detect_fvgs(bars, Timeframe.M5)
    resolve_fills(fvgs, bars)
    once = [f.filled for f in fvgs]
    resolve_fills(fvgs, bars)  # a second pass must not change anything
    assert [f.filled for f in fvgs] == once
