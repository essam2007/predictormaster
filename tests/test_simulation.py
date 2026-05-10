from __future__ import annotations

import numpy as np

from predictormaster.simulation.monte_carlo import simulate_poisson, variance_decomposition
from predictormaster.simulation.particle_filter import ParticleFilter


def test_simulate_poisson_probabilities_consistent():
    sim = simulate_poisson(lam_home=1.6, lam_away=1.0, n_sims=100_000, seed=0)
    total = sim.p_home + sim.p_draw + sim.p_away
    assert abs(total - 1.0) < 1e-6
    assert sim.p_home > sim.p_away  # home stronger
    assert abs(sim.expected_score_home - 1.6) < 0.05
    assert abs(sim.expected_score_away - 1.0) < 0.05


def test_variance_decomposition_recovers_components():
    rng = np.random.default_rng(0)
    samples = [rng.normal(loc, 1.0, size=2000) for loc in [-1, 0, 1]]
    out = variance_decomposition(samples)
    assert abs(out["aleatoric"] - 1.0) < 0.1
    assert abs(out["epistemic"] - np.var([-1, 0, 1])) < 0.05


def test_particle_filter_tracks_const_state():
    rng = np.random.default_rng(0)
    n = 500
    particles = rng.normal(0.0, 5.0, size=n)

    def transition(p, _rng):
        return p + _rng.normal(0, 0.05, size=p.shape)

    def loglik(p, y):
        return -0.5 * (y[0] - p) ** 2 / 0.5

    pf = ParticleFilter(
        transition=transition,
        log_likelihood=loglik,
        particles=particles,
        log_weights=np.zeros(n),
    )
    truth = 2.5
    for _ in range(50):
        y = np.array([truth + rng.normal(0, 0.7)])
        pf.step(y, rng=rng)
    mean, _ = pf.estimate()
    assert abs(float(mean) - truth) < 0.5
