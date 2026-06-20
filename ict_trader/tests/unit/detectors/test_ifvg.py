from __future__ import annotations

from tests.conftest import series_from

from ict_trader.detectors.fvg import detect_fvgs
from ict_trader.detectors.ifvg import LTFTriggerDetector, find_inversions
from ict_trader.domain.enums import PDArrayKind, Side, Timeframe


def _bearish_fvg_then_bodyclose_above():
    # First create a bearish FVG, then a candle whose BODY closes above its upper bound.
    return series_from([
        (20, 21, 19, 19.5),     # c1 low 19
        (18.8, 19, 16, 16.5),   # c2
        (16.4, 17, 15, 15.5),   # c3 high 17 < c1 low 19 -> bearish FVG [17, 19]
        (15.6, 16, 15, 15.8),
        (16, 18, 15.9, 17.5),   # wick into gap but close 17.5 < 19 (no inversion yet)
        (17.6, 20, 17.5, 19.5),  # body close 19.5 > 19 -> inversion to bullish IFVG
    ])


def test_body_close_inverts_fvg():
    bars = _bearish_fvg_then_bodyclose_above()
    fvgs = detect_fvgs(bars, Timeframe.M3)
    ifvgs = find_inversions(bars, fvgs)
    assert len(ifvgs) == 1
    assert ifvgs[0].side is Side.LONG
    assert ifvgs[0].kind is PDArrayKind.IFVG
    assert ifvgs[0].origin_ts is not None


def test_wick_only_does_not_invert():
    # Same setup but the final candle only WICKS above the gap (close stays inside).
    bars = series_from([
        (20, 21, 19, 19.5),
        (18.8, 19, 16, 16.5),
        (16.4, 17, 15, 15.5),    # bearish FVG [17,19]
        (15.6, 16, 15, 15.8),
        (16, 20, 15.9, 18.5),    # wick to 20 but close 18.5 < 19 -> NO inversion
    ])
    fvgs = detect_fvgs(bars, Timeframe.M3)
    assert find_inversions(bars, fvgs) == []


def test_trigger_detector_emits_entry_and_stop():
    bars = _bearish_fvg_then_bodyclose_above()
    det = LTFTriggerDetector(stop_buffer_ticks=2)
    st = det.update(bars, Timeframe.M3, Side.LONG)
    assert st.present is True
    assert "entry" in st.payload and "stop" in st.payload
    # long stop must sit below entry
    assert st.payload["stop"] < st.payload["entry"]
