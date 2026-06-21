"""Short-side coverage: the long side is well tested; mirror the key detectors for shorts."""

from __future__ import annotations

from tests.conftest import mk_bar, series_from

from ict_trader.detectors.fvg import detect_fvgs
from ict_trader.detectors.ifvg import LTFTriggerDetector, find_inversions
from ict_trader.detectors.lrlr import LRLRDetector, obstacles_in_path
from ict_trader.detectors.psp import PSPDetector
from ict_trader.detectors.structure import analyze
from ict_trader.domain.bars import CoBar
from ict_trader.domain.enums import PDArrayKind, Side, Symbol, Timeframe
from ict_trader.domain.pdarrays import FVG


def test_bullish_fvg_bodyclose_below_inverts_to_bearish_ifvg():
    # rising 3 candles leave a bullish FVG, then a body close BELOW it flips to bearish IFVG
    bars = series_from([
        (10, 11, 9.5, 10.5),     # c1 high 11
        (10.5, 13, 10.4, 12.5),  # c2
        (12.6, 14, 12, 13.5),    # c3 low 12 > c1 high 11 -> bullish FVG [11, 12]
        (12, 12.2, 10, 10.5),    # body close 10.5 < 11 -> bearish IFVG
    ])
    fvgs = detect_fvgs(bars, Timeframe.M3)
    ifvgs = find_inversions(bars, fvgs)
    assert len(ifvgs) == 1
    assert ifvgs[0].side is Side.SHORT and ifvgs[0].kind is PDArrayKind.IFVG


def test_ltf_trigger_short_emits_entry_above_stop():
    bars = series_from([
        (10, 11, 9.5, 10.5), (10.5, 13, 10.4, 12.5), (12.6, 14, 12, 13.5),
        (12, 12.2, 10, 10.5),
    ])
    st = LTFTriggerDetector(stop_buffer_ticks=2).update(bars, Timeframe.M3, Side.SHORT)
    assert st.present is True
    # for a short, the protective stop sits ABOVE the entry
    assert st.payload["stop"] > st.payload["entry"]


def test_lrlr_short_congested_vs_clean():
    det = LRLRDetector()
    ts = series_from([(0, 1, 0, 0.5)])[0].ts_open
    bull = FVG(side=Side.LONG, timeframe=Timeframe.M5, ts=ts, lower=104, upper=105)
    bear = FVG(side=Side.SHORT, timeframe=Timeframe.M5, ts=ts, lower=104, upper=105)
    # short runs 110 -> 100; an opposing (bullish) array in the lane = congested
    assert det.update(entry=110, target=100, side=Side.SHORT, arrays=[bull]).present is False
    # only a supporting (bearish) array in the lane = clean
    assert det.update(entry=110, target=100, side=Side.SHORT, arrays=[bear]).present is True


def test_obstacles_short_ignores_arrays_outside_lane():
    ts = series_from([(0, 1, 0, 0.5)])[0].ts_open
    below = FVG(side=Side.LONG, timeframe=Timeframe.M5, ts=ts, lower=90, upper=91)
    assert obstacles_in_path(110, 100, Side.SHORT, [below]) == []


def test_structure_bos_short():
    bars = series_from([
        (20, 20.5, 19, 19.5), (19.5, 20, 18, 18.5), (18.5, 19, 17, 17.5),  # swing low 17
        (17.6, 19, 17.8, 18.8), (18.8, 19.5, 18, 19),
        (19, 19.2, 16.5, 16.8),  # close 16.8 < swing low 17 -> BOS (short)
    ])
    view = analyze(bars, Side.SHORT, strength=1)
    assert view.bos is True


def test_psp_short_bias_agreement():
    # bearish setup: ES closes up, NQ closes down -> short agrees
    es = mk_bar(0, 10, 11, 9.9, 10.8, symbol=Symbol.ES)
    nq = mk_bar(0, 10, 10.1, 9, 9.2, symbol=Symbol.NQ)
    cobar = CoBar(ts_open=es.ts_open, timeframe=Timeframe.M5, es=es, nq=nq)
    st = PSPDetector().update(cobar, Side.SHORT, inside_htf_fvg=False)
    assert st.present is True
    assert st.payload["nq_dir"] == "short" and st.payload["es_dir"] == "long"
