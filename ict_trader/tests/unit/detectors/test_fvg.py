from __future__ import annotations

from tests.conftest import series_from

from ict_trader.detectors.fvg import FVGDetector, detect_fvgs, resolve_fills
from ict_trader.domain.enums import Side, Timeframe


def test_bullish_fvg_detected():
    # c1 high=10, c2 pushes up, c3 low=12 -> gap [10, 12]
    bars = series_from([
        (9, 10, 8, 9.5),     # c1: high 10
        (9.6, 13, 9.4, 12.5),  # c2
        (12.6, 14, 12, 13.5),  # c3: low 12 > c1 high 10 -> bullish FVG
    ])
    fvgs = detect_fvgs(bars, Timeframe.M5)
    assert len(fvgs) == 1
    f = fvgs[0]
    assert f.side is Side.LONG
    assert f.lower == 10 and f.upper == 12
    assert f.mid == 11


def test_bearish_fvg_detected():
    bars = series_from([
        (9, 11, 9, 9.5),       # c1: low 9
        (8.8, 9.0, 6, 6.5),    # c2
        (6.4, 7, 5, 5.5),      # c3: high 7 < c1 low 9 -> bearish FVG [7, 9]
    ])
    fvgs = detect_fvgs(bars, Timeframe.M5)
    assert len(fvgs) == 1 and fvgs[0].side is Side.SHORT
    assert fvgs[0].lower == 7 and fvgs[0].upper == 9


def test_min_ticks_filters_tiny_gaps():
    # gap of exactly 0.25 (1 tick); require 4 ticks -> filtered out
    bars = series_from([
        (9, 10.0, 8, 9.5),
        (9.6, 11, 9.4, 10.5),
        (10.3, 11, 10.25, 10.8),  # low 10.25 > high 10.0 by 0.25
    ])
    assert detect_fvgs(bars, Timeframe.M5, min_ticks=4) == []
    assert len(detect_fvgs(bars, Timeframe.M5, min_ticks=1)) == 1


def test_resolve_fills_only_on_full_throughclose():
    # A reaction that merely taps the gap and closes back inside does NOT mitigate it...
    reacting = series_from([
        (9, 10, 8, 9.5),
        (9.6, 13, 9.4, 12.5),
        (12.6, 14, 12, 13.5),    # bullish FVG [10,12]
        (13.5, 13.6, 10.5, 11),  # low 10.5 into gap but close 11 inside -> still holds
    ])
    fvgs = detect_fvgs(reacting, Timeframe.M5)
    resolve_fills(fvgs, reacting)
    assert fvgs[0].filled is False

    # ...but a body close below the lower bound invalidates it.
    through = series_from([
        (9, 10, 8, 9.5),
        (9.6, 13, 9.4, 12.5),
        (12.6, 14, 12, 13.5),
        (13.5, 13.6, 9, 9.4),    # close 9.4 < lower 10 -> mitigated
    ])
    fvgs2 = detect_fvgs(through, Timeframe.M5)
    resolve_fills(fvgs2, through)
    assert fvgs2[0].filled is True


def test_detector_present_for_long_in_discount():
    # Build a down-then-FVG sequence so a bullish FVG sits in the discount half and price
    # is delivering into it.
    rows = [
        (20, 20, 18, 18.5),
        (18, 18.2, 16, 16.5),
        (16, 16.2, 14, 14.5),
        (14, 14.2, 12, 12.5),   # lows make discount region low
        (12.5, 12.7, 11, 11.5),
        (11.4, 11.6, 10, 10.2),  # c1 high ~11.6
        (10.3, 13.5, 10.2, 13),  # c2 strong up
        (13.1, 14, 12.0, 12.2),  # c3 low 12 > c1 high 11.6 -> bullish FVG [11.6,12]
        (12.2, 12.3, 11.7, 11.9),  # price delivers DOWN into the discount gap (low 11.7)
    ]
    bars = series_from(rows)
    det = FVGDetector()
    st = det.update(bars, Timeframe.M15, Side.LONG)
    assert st.present is True
    assert st.bias is Side.LONG
    assert st.payload["lower"] < st.payload["upper"]
