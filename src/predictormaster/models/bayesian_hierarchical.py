"""Bayesian hierarchical Poisson model for team scoring.

Generative process

    sigma_a, sigma_b ~ HalfNormal(1)
    alpha_t ~ Normal(0, sigma_a^2)             [attack strengths]
    beta_t  ~ Normal(0, sigma_b^2)             [defence strengths]
    gamma   ~ Normal(0, 1)                      [home advantage]
    lambda_i = exp(alpha_h + beta_a + gamma)
    mu_i     = exp(alpha_a + beta_h)
    home_goals_i ~ Poisson(lambda_i)
    away_goals_i ~ Poisson(mu_i)

This file ships a NumPy/SciPy MAP fit with Laplace posterior approximation;
when PyMC is installed the `fit_pymc` function returns a full NUTS posterior.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize


@dataclass
class HierarchicalFit:
    teams: list[str]
    alpha: np.ndarray
    beta: np.ndarray
    gamma: float
    sigma_a: float
    sigma_b: float
    posterior_cov: np.ndarray
    log_posterior: float


def _neg_log_posterior(theta: np.ndarray, h: np.ndarray, a: np.ndarray, hg: np.ndarray, ag: np.ndarray, n: int) -> float:
    alpha = theta[:n]
    beta = theta[n : 2 * n]
    gamma = theta[2 * n]
    log_sa = theta[2 * n + 1]
    log_sb = theta[2 * n + 2]
    sa = np.exp(log_sa)
    sb = np.exp(log_sb)

    lam = np.exp(alpha[h] + beta[a] + gamma)
    mu = np.exp(alpha[a] + beta[h])

    log_lik = np.sum(hg * np.log(lam) - lam) + np.sum(ag * np.log(mu) - mu)
    log_prior = (
        -0.5 * np.sum((alpha / sa) ** 2)
        - n * log_sa
        - 0.5 * np.sum((beta / sb) ** 2)
        - n * log_sb
        - 0.5 * gamma**2
        - 0.5 * (sa**2 + sb**2)  # half-normal(1) prior log-density up to const
    )
    return float(-(log_lik + log_prior))


def fit_hierarchical_map(
    *, home: list[str], away: list[str], home_goals: list[int], away_goals: list[int]
) -> HierarchicalFit:
    teams = sorted(set(home) | set(away))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    h = np.array([idx[t] for t in home])
    a = np.array([idx[t] for t in away])
    hg = np.asarray(home_goals, dtype=float)
    ag = np.asarray(away_goals, dtype=float)

    theta0 = np.zeros(2 * n + 3)
    theta0[2 * n] = 0.25
    theta0[2 * n + 1] = np.log(0.3)
    theta0[2 * n + 2] = np.log(0.3)

    res = minimize(
        _neg_log_posterior,
        theta0,
        args=(h, a, hg, ag, n),
        method="L-BFGS-B",
    )
    cov = _laplace_cov(res.x, h, a, hg, ag, n)
    return HierarchicalFit(
        teams=teams,
        alpha=res.x[:n],
        beta=res.x[n : 2 * n],
        gamma=float(res.x[2 * n]),
        sigma_a=float(np.exp(res.x[2 * n + 1])),
        sigma_b=float(np.exp(res.x[2 * n + 2])),
        posterior_cov=cov,
        log_posterior=-float(res.fun),
    )


def _laplace_cov(theta: np.ndarray, h: np.ndarray, a: np.ndarray, hg: np.ndarray, ag: np.ndarray, n: int) -> np.ndarray:
    """Numerical Hessian for Laplace approximation."""
    eps = 1e-4
    p = len(theta)
    H = np.zeros((p, p))
    for i in range(p):
        for j in range(i, p):
            t_pp = theta.copy()
            t_pp[i] += eps
            t_pp[j] += eps
            t_pm = theta.copy()
            t_pm[i] += eps
            t_pm[j] -= eps
            t_mp = theta.copy()
            t_mp[i] -= eps
            t_mp[j] += eps
            t_mm = theta.copy()
            t_mm[i] -= eps
            t_mm[j] -= eps
            f_pp = _neg_log_posterior(t_pp, h, a, hg, ag, n)
            f_pm = _neg_log_posterior(t_pm, h, a, hg, ag, n)
            f_mp = _neg_log_posterior(t_mp, h, a, hg, ag, n)
            f_mm = _neg_log_posterior(t_mm, h, a, hg, ag, n)
            H[i, j] = (f_pp - f_pm - f_mp + f_mm) / (4 * eps * eps)
            H[j, i] = H[i, j]
    # Posterior covariance is inverse Hessian of negative log posterior.
    try:
        return np.linalg.inv(H + 1e-6 * np.eye(p))
    except np.linalg.LinAlgError:
        return np.linalg.pinv(H)


def fit_pymc(*, home, away, home_goals, away_goals, draws=1000, tune=1000):  # pragma: no cover
    """Full NUTS posterior. Optional, requires PyMC."""
    import pymc as pm

    teams = sorted(set(home) | set(away))
    idx = {t: i for i, t in enumerate(teams)}
    h = np.array([idx[t] for t in home])
    a = np.array([idx[t] for t in away])
    n = len(teams)

    with pm.Model():
        sigma_a = pm.HalfNormal("sigma_a", 1.0)
        sigma_b = pm.HalfNormal("sigma_b", 1.0)
        alpha = pm.Normal("alpha", 0.0, sigma_a, shape=n)
        beta = pm.Normal("beta", 0.0, sigma_b, shape=n)
        gamma = pm.Normal("gamma", 0.0, 1.0)
        lam = pm.math.exp(alpha[h] + beta[a] + gamma)
        mu = pm.math.exp(alpha[a] + beta[h])
        pm.Poisson("hg", lam, observed=home_goals)
        pm.Poisson("ag", mu, observed=away_goals)
        idata = pm.sample(draws=draws, tune=tune, progressbar=False)
    return idata
