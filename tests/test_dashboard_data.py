from datetime import date, timedelta

import numpy as np

from dashboards._data import (
    SPORTS,
    generate_matches,
    run_kalman,
    simulate_strategy,
)


def test_generator_is_deterministic_per_seed():
    start = date(2025, 1, 1)
    end = start + timedelta(days=60)
    a = generate_matches("nba", start, end, seed=7)
    b = generate_matches("nba", start, end, seed=7)
    assert a.matches.equals(b.matches)
    c = generate_matches("nba", start, end, seed=8)
    assert not a.matches.equals(c.matches)


def test_kalman_trace_shape_matches_match_days():
    start = date(2025, 1, 1)
    end = start + timedelta(days=90)
    mf = generate_matches("epl", start, end, seed=1)
    trace = run_kalman(mf, q=0.02, r=0.5)
    n_teams = mf.strengths.shape[1]
    n_days = len(trace.timestamps)
    assert trace.posterior_mean.shape == (n_days, n_teams)
    assert trace.posterior_var.shape == (n_days, n_teams)
    assert (trace.posterior_var >= 0).all()


def test_strategy_runs_and_emits_metrics():
    start = date(2025, 1, 1)
    end = start + timedelta(days=120)
    mf = generate_matches("nba", start, end, seed=3)
    trace = run_kalman(mf, q=0.02, r=0.5)
    res = simulate_strategy(mf, trace, edge_threshold=0.0, bet_fraction=0.01, seed=3)
    assert res.n_bets > 0
    assert np.isfinite(res.sharpe)
    assert np.isfinite(res.max_drawdown)
    assert 0.0 <= res.win_rate <= 1.0


def test_all_sports_generate_nonempty():
    start = date(2025, 1, 1)
    end = start + timedelta(days=90)
    for sport in SPORTS:
        mf = generate_matches(sport, start, end, seed=0)
        assert len(mf.matches) > 0, sport
