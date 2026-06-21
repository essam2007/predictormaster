from __future__ import annotations

from datetime import date

from tests.conftest import mk_bar, series_from

from ict_trader.detectors.liquidity import LiquidityState, _cluster
from ict_trader.detectors.quarterly import refine_amd
from ict_trader.domain.enums import AMDPhase, Side


def test_refine_amd_distribution_on_strong_move():
    # strong one-directional expansion -> distribution regardless of base label
    bars = series_from([
        (100, 102, 99.8, 101.5), (101.5, 104, 101, 103.5), (103.5, 106, 103, 105.5),
        (105.5, 108, 105, 107.5), (107.5, 110, 107, 109.5), (109.5, 112, 109, 111.5),
    ])
    assert refine_amd(0, bars) is AMDPhase.DISTRIBUTION


def test_refine_amd_manipulation_on_sweep_then_revert():
    # sweep the early low, then close back inside with little net move -> manipulation
    bars = series_from([
        (100, 101, 99, 100.5), (100.5, 101, 99.5, 100),   # first third: min low 99
        (100, 100.5, 97, 98),                              # sweeps below 99
        (98, 100, 97.5, 99.5), (99.5, 100.5, 99, 100), (100, 100.8, 99.5, 100.2),
    ])
    assert refine_amd(2, bars) is AMDPhase.MANIPULATION


def test_refine_amd_falls_back_with_too_few_bars():
    bars = series_from([(100, 101, 99, 100.5), (100.5, 101, 100, 100.8)])
    assert refine_amd(0, bars) is AMDPhase.ACCUMULATION  # base for quarter 0


def test_cluster_groups_near_equal_levels():
    assert _cluster([100.0, 100.1, 105.0], tol=0.5) == [100.0]
    assert _cluster([100.0], tol=0.5) == []  # a lone level is not a pool


def test_liquidity_state_tracks_day_and_prior_day():
    liq = LiquidityState()
    d1 = date(2024, 5, 14)
    liq.update(mk_bar(0, 100, 102, 99, 101), d1)
    liq.update(mk_bar(1, 101, 105, 100, 104), d1)
    assert liq.day_high == 105 and liq.day_low == 99
    assert liq.erl_target(Side.LONG) == 105 and liq.erl_target(Side.SHORT) == 99
    # new day rolls prior-day levels
    liq.update(mk_bar(2, 104, 106, 103, 105), date(2024, 5, 15))
    assert liq.prior_day_high == 105 and liq.prior_day_low == 99
    assert liq.day_high == 106 and liq.day_low == 103


def test_daily_extreme_in():
    liq = LiquidityState()
    liq.update(mk_bar(0, 100, 110, 95, 108), date(2024, 5, 15))
    assert liq.daily_extreme_in(Side.LONG, latest_close=110) is True   # at the high
    assert liq.daily_extreme_in(Side.LONG, latest_close=104) is False  # room to run up
    assert liq.daily_extreme_in(Side.SHORT, latest_close=95) is True   # at the low
