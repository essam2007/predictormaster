"""Property tests for Dixon-Coles."""
from __future__ import annotations

import numpy as np
from scipy.optimize import approx_fprime

from predictormaster.models.dixon_coles import (
    _neg_loglik,
    _neg_loglik_grad,
    fit_dixon_coles,
)


def _simulate(rng: np.random.Generator, n: int = 800) -> dict:
    teams = [f"t{i}" for i in range(8)]
    true_alpha = rng.normal(0, 0.4, len(teams))
    true_alpha -= true_alpha.mean()
    true_beta = rng.normal(0, 0.3, len(teams))
    gamma = 0.3
    home, away, hg, ag = [], [], [], []
    for _ in range(n):
        i, j = rng.choice(len(teams), size=2, replace=False)
        lam = np.exp(true_alpha[i] + true_beta[j] + gamma)
        mu = np.exp(true_alpha[j] + true_beta[i])
        home.append(teams[i])
        away.append(teams[j])
        hg.append(int(rng.poisson(lam)))
        ag.append(int(rng.poisson(mu)))
    return {
        "home": home,
        "away": away,
        "home_goals": hg,
        "away_goals": ag,
        "true_alpha": true_alpha,
        "teams": teams,
    }


def test_dixon_coles_recovers_attack_ranking():
    rng = np.random.default_rng(7)
    data = _simulate(rng, n=1000)
    fit = fit_dixon_coles(
        home=data["home"],
        away=data["away"],
        home_goals=data["home_goals"],
        away_goals=data["away_goals"],
    )
    assert fit.converged
    rho = float(np.corrcoef(fit.attack, data["true_alpha"])[0, 1])
    assert rho > 0.85


def test_outcome_probs_sum_to_one():
    rng = np.random.default_rng(0)
    data = _simulate(rng, n=400)
    fit = fit_dixon_coles(
        home=data["home"],
        away=data["away"],
        home_goals=data["home_goals"],
        away_goals=data["away_goals"],
    )
    p_h, p_d, p_a = fit.outcome_probs(data["teams"][0], data["teams"][1])
    assert abs(p_h + p_d + p_a - 1.0) < 1e-6
    assert 0 <= p_h <= 1 and 0 <= p_d <= 1 and 0 <= p_a <= 1


def test_analytic_gradient_matches_finite_difference():
    rng = np.random.default_rng(2)
    n_teams = 5
    home_idx = rng.integers(0, n_teams, size=300)
    away_idx = rng.integers(0, n_teams, size=300)
    hg = rng.poisson(1.5, size=300).astype(float)
    ag = rng.poisson(1.0, size=300).astype(float)
    weights = np.ones(300)
    theta = np.concatenate(
        [rng.normal(0, 0.2, n_teams - 1), rng.normal(0, 0.2, n_teams), [0.25, -0.05]]
    )
    args = (home_idx, away_idx, hg, ag, n_teams, weights)
    g_a = _neg_loglik_grad(theta, *args)
    g_n = approx_fprime(theta, _neg_loglik, 1e-6, *args)
    assert np.max(np.abs(g_a - g_n)) < 1e-3


def test_score_pmf_normalised():
    rng = np.random.default_rng(1)
    data = _simulate(rng, n=400)
    fit = fit_dixon_coles(
        home=data["home"], away=data["away"],
        home_goals=data["home_goals"], away_goals=data["away_goals"],
    )
    pmf = fit.score_pmf(data["teams"][0], data["teams"][1], max_goals=8)
    assert abs(pmf.sum() - 1.0) < 1e-6
    assert (pmf >= 0).all()
