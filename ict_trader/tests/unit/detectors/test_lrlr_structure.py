from __future__ import annotations

from tests.conftest import series_from

from ict_trader.detectors.lrlr import LRLRDetector, obstacles_in_path
from ict_trader.detectors.structure import analyze
from ict_trader.domain.enums import Side, Timeframe
from ict_trader.domain.pdarrays import FVG


def _bear_fvg(lower, upper, ts_index=0):
    bars = series_from([(0, 1, 0, 0.5)])
    return FVG(side=Side.SHORT, timeframe=Timeframe.M5, ts=bars[0].ts_open,
               lower=lower, upper=upper)


def test_clean_path_when_no_opposing_arrays():
    det = LRLRDetector()
    # long from 100 to 110, only a SUPPORTING (bullish) array in the way -> clean
    arrays = [FVG(side=Side.LONG, timeframe=Timeframe.M5,
                  ts=series_from([(0, 1, 0, 0.5)])[0].ts_open, lower=103, upper=104)]
    st = det.update(entry=100, target=110, side=Side.LONG, arrays=arrays)
    assert st.present is True and st.payload["path_clean"] is True


def test_congested_path_when_opposing_array_in_lane():
    det = LRLRDetector()
    arrays = [_bear_fvg(104, 105)]  # bearish array between 100 and 110 -> resistance
    st = det.update(entry=100, target=110, side=Side.LONG, arrays=arrays)
    assert st.present is False
    assert st.payload["n_obstacles"] == 1


def test_obstacles_ignores_arrays_outside_lane():
    arrays = [_bear_fvg(120, 121)]  # above target -> not in lane
    assert obstacles_in_path(100, 110, Side.LONG, arrays) == []


def test_structure_bos_long():
    # rising series that closes above the prior swing high
    rows = [
        (10, 11, 9, 10.5), (10.5, 12, 10, 11.5), (11.5, 13, 11, 11.2),  # swing high 13
        (11.2, 12, 10.5, 11), (11, 11.5, 10.2, 10.8),
        (10.8, 13.5, 10.6, 13.4),  # close 13.4 > swing high 13 -> BOS
    ]
    bars = series_from(rows)
    view = analyze(bars, Side.LONG, strength=1)
    assert view.bos is True
    assert view.trail_to is not None
