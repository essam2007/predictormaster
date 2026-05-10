"""Performance regression harness, gated by `-m bench`.

Run locally with::

    pytest -m bench --benchmark-only

Run in CI via the dedicated `bench` job. Failures here are advisory: a
single hot path regressing more than 25 % vs the committed baseline
should block promotion of the corresponding model version, but it does
not block ordinary unit-test CI.
"""
from __future__ import annotations

import numpy as np
import pytest

from predictormaster.models.dixon_coles import fit_dixon_coles
from predictormaster.models.hmm import baum_welch
from predictormaster.simulation.monte_carlo import simulate_poisson, simulate_possessions
from predictormaster.validation.calibration import expected_calibration_error
from predictormaster.validation.drift import ADWIN

pytestmark = pytest.mark.bench


@pytest.fixture(scope="module")
def dixon_coles_data():
    rng = np.random.default_rng(0)
    teams = [f"t{i}" for i in range(8)]
    home, away, hg, ag = [], [], [], []
    for _ in range(1000):
        i, j = rng.choice(len(teams), size=2, replace=False)
        home.append(teams[i])
        away.append(teams[j])
        hg.append(int(rng.poisson(1.4)))
        ag.append(int(rng.poisson(1.0)))
    return home, away, hg, ag


def test_bench_dixon_coles(benchmark, dixon_coles_data):
    home, away, hg, ag = dixon_coles_data
    benchmark(
        lambda: fit_dixon_coles(home=home, away=away, home_goals=hg, away_goals=ag)
    )


def test_bench_simulate_poisson(benchmark):
    benchmark(lambda: simulate_poisson(lam_home=1.6, lam_away=1.0, n_sims=50_000, seed=0))


def test_bench_simulate_possessions(benchmark):
    benchmark(
        lambda: simulate_possessions(
            n_possessions=100,
            home_score_prob=0.55,
            away_score_prob=0.5,
            n_sims=10_000,
            seed=0,
        )
    )


def test_bench_ece(benchmark):
    rng = np.random.default_rng(0)
    n = 50_000
    p = rng.uniform(0, 1, size=n)
    y = rng.binomial(1, p)
    benchmark(lambda: expected_calibration_error(p, y, n_bins=15))


def test_bench_baum_welch(benchmark):
    rng = np.random.default_rng(0)
    obs = rng.integers(0, 4, size=2000)
    benchmark(lambda: baum_welch(obs, n_states=3, n_symbols=4, n_iter=8))


def test_bench_adwin(benchmark):
    rng = np.random.default_rng(0)
    stream = rng.normal(0.0, 0.1, size=20_000)

    def run():
        a = ADWIN(delta=0.001)
        for x in stream:
            a.update(float(x))

    benchmark(run)
