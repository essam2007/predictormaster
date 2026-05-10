from __future__ import annotations

import numpy as np

from predictormaster.models.elo import EloRater
from predictormaster.models.glicko import Glicko2


def test_elo_zero_sum():
    r = EloRater()
    h0, a0 = r.get("a"), r.get("b")
    h1, a1 = r.update(home="a", away="b", home_score=2, away_score=0)
    assert abs((h1 - h0) + (a1 - a0)) < 1e-9


def test_elo_expected_in_unit_interval():
    r = EloRater()
    p = r.expected("x", "y")
    assert 0.0 < p < 1.0


def test_elo_expected_higher_for_home():
    r = EloRater()
    r.ratings["x"] = 1500
    r.ratings["y"] = 1500
    assert r.expected("x", "y") > 0.5


def test_glicko_volatility_step():
    g = Glicko2()
    g.update("p", [("o1", 1.0), ("o2", 0.0), ("o3", 1.0)])
    st = g.state("p")
    assert st.rd < 350.0  # rating deviation should drop after observations
    assert 0.0 < st.sigma < 1.0


def test_glicko_no_results_inflates_rd():
    g = Glicko2()
    rd0 = g.state("p").rd
    g.update("p", [])
    assert g.state("p").rd > rd0
