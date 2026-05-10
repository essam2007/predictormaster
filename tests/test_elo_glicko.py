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


def test_elo_batch_zero_sum_over_round():
    r = EloRater()
    home = ["a", "b", "c", "a"]
    away = ["b", "c", "a", "c"]
    hs = np.array([2.0, 1.0, 0.0, 3.0])
    as_ = np.array([1.0, 1.0, 2.0, 0.0])
    before = sum(r.get(t) for t in set(home + away))
    r.update_batch(home, away, hs, as_)
    after = sum(r.get(t) for t in set(home + away))
    assert abs(before - after) < 1e-9


def test_elo_batch_matches_sequential_when_no_team_repeats():
    seq = EloRater()
    bat = EloRater()
    home = ["a", "c", "e"]
    away = ["b", "d", "f"]
    hs = np.array([2.0, 0.0, 1.0])
    as_ = np.array([1.0, 1.0, 0.0])
    for h, a, sh, sa in zip(home, away, hs, as_, strict=True):
        seq.update(home=h, away=a, home_score=sh, away_score=sa)
    bat.update_batch(home, away, hs, as_)
    for t in set(home + away):
        assert abs(seq.get(t) - bat.get(t)) < 1e-9


def test_glicko_batch_matches_period_semantics():
    g_seq = Glicko2()
    g_bat = Glicko2()
    period = {
        "p": [("o1", 1.0), ("o2", 0.0)],
        "q": [("o3", 0.5)],
    }
    # Sequential application reads the same opponent state because Glicko-2
    # is period-batched: opponents are not updated within a period.
    g_seq.update("p", period["p"])
    g_seq.update("q", period["q"])
    g_bat.update_batch(period)
    for player in ("p", "q"):
        sst = g_seq.state(player)
        bst = g_bat.state(player)
        assert abs(sst.rating - bst.rating) < 1e-9
        assert abs(sst.rd - bst.rd) < 1e-9
