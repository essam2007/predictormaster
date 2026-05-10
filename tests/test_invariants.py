"""Property-based invariant tests via Hypothesis."""
from __future__ import annotations

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from predictormaster.models.elo import EloRater
from predictormaster.simulation.monte_carlo import simulate_poisson
from predictormaster.simulation.particle_filter import ParticleFilter, systematic_resample
from predictormaster.validation.calibration import (
    brier_decomposition,
    expected_calibration_error,
    log_loss,
)
from predictormaster.validation.drift import ADWIN


@given(
    lam=st.floats(0.05, 5.0),
    mu=st.floats(0.05, 5.0),
    seed=st.integers(0, 2**16 - 1),
)
@settings(max_examples=30, deadline=None)
def test_simulate_poisson_probabilities_simplex(lam: float, mu: float, seed: int):
    sim = simulate_poisson(lam_home=lam, lam_away=mu, n_sims=5_000, seed=seed)
    s = sim.p_home + sim.p_draw + sim.p_away
    assert abs(s - 1.0) < 1e-9
    assert 0.0 <= sim.p_home <= 1.0
    assert 0.0 <= sim.p_draw <= 1.0
    assert 0.0 <= sim.p_away <= 1.0


@given(
    n=st.integers(50, 2_000),
    seed=st.integers(0, 2**16 - 1),
)
@settings(max_examples=20, deadline=None)
def test_brier_in_unit_interval(n: int, seed: int):
    rng = np.random.default_rng(seed)
    p = rng.uniform(0, 1, size=n)
    y = rng.binomial(1, p)
    rep = expected_calibration_error(p, y, n_bins=10)
    assert 0.0 <= rep.brier <= 1.0
    rel, res, unc = brier_decomposition(p, y, n_bins=10)
    assert rel >= -1e-9 and res >= -1e-9 and 0.0 <= unc <= 0.25


@given(
    n=st.integers(20, 500),
    seed=st.integers(0, 2**16 - 1),
)
@settings(max_examples=20, deadline=None)
def test_log_loss_strictly_proper(n: int, seed: int):
    rng = np.random.default_rng(seed)
    y = rng.binomial(1, 0.5, size=n)
    bad = np.full(n, 0.5)
    truth_aware = np.where(y == 1, 0.9, 0.1)
    assert log_loss(truth_aware, y) <= log_loss(bad, y) + 1e-9


@given(
    score_home=st.lists(st.integers(0, 5), min_size=2, max_size=8),
    score_away=st.lists(st.integers(0, 5), min_size=2, max_size=8),
    seed=st.integers(0, 2**16 - 1),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.filter_too_much])
def test_elo_batch_zero_sum(score_home, score_away, seed):
    n = min(len(score_home), len(score_away))
    score_home = score_home[:n]
    score_away = score_away[:n]
    rng = np.random.default_rng(seed)
    teams = [f"t{i}" for i in range(2 * n)]
    home = teams[:n]
    away = teams[n:]
    r = EloRater()
    before = sum(r.get(t) for t in teams)
    r.update_batch(
        home,
        away,
        np.asarray(score_home, dtype=float),
        np.asarray(score_away, dtype=float),
    )
    after = sum(r.get(t) for t in teams)
    assert abs(before - after) < 1e-7


@given(weights=st.lists(st.floats(1e-6, 10.0), min_size=4, max_size=64))
@settings(max_examples=30, deadline=None)
def test_systematic_resample_indices_in_range(weights: list[float]):
    rng = np.random.default_rng(0)
    w = np.asarray(weights)
    w = w / w.sum()
    idx = systematic_resample(w, rng=rng)
    assert idx.shape == w.shape
    assert idx.min() >= 0 and idx.max() < len(w)


@given(
    n_pre=st.integers(50, 400),
    n_post=st.integers(50, 400),
    shift=st.floats(0.5, 2.0),
    seed=st.integers(0, 2**16 - 1),
)
@settings(max_examples=10, deadline=None)
def test_adwin_window_shrinks_after_drift(n_pre, n_post, shift, seed):
    rng = np.random.default_rng(seed)
    a = ADWIN(delta=0.001)
    for x in rng.normal(0.0, 0.1, size=n_pre):
        a.update(float(x))
    pre_size = a.size
    drift_at = None
    for i, x in enumerate(rng.normal(shift, 0.1, size=n_post)):
        if a.update(float(x)) and drift_at is None:
            drift_at = i
            break
    if drift_at is not None:
        # After a detected cut the window must contain fewer samples than
        # what we had just before drift was raised.
        assert a.size <= pre_size + drift_at


def test_particle_filter_threshold_validation():
    import pytest

    with pytest.raises(ValueError):
        ParticleFilter(
            transition=lambda p, _r: p,
            log_likelihood=lambda p, y: np.zeros(len(p)),
            particles=np.zeros(10),
            log_weights=np.zeros(10),
            resample_threshold=0.0,
        )
    with pytest.raises(ValueError):
        ParticleFilter(
            transition=lambda p, _r: p,
            log_likelihood=lambda p, y: np.zeros(len(p)),
            particles=np.zeros(10),
            log_weights=np.zeros(10),
            resample_threshold=1.5,
        )
