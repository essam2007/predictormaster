"""Dixon-Coles bivariate Poisson model for low-scoring sports.

Likelihood (per match i with home score x_i, away score y_i):

    P(x_i, y_i) = tau(x_i, y_i; lambda_i, mu_i, rho)
                  * Poisson(x_i; lambda_i) * Poisson(y_i; mu_i)

with intensities

    lambda_i = exp(alpha_{h(i)} + beta_{a(i)} + gamma)
    mu_i     = exp(alpha_{a(i)} + beta_{h(i)})

and the low-score correction

    tau(0,0) = 1 - lambda*mu*rho
    tau(0,1) = 1 + lambda*rho
    tau(1,0) = 1 + mu*rho
    tau(1,1) = 1 - rho
    tau(.,.) = 1                 otherwise.

We impose the standard identifiability constraint  sum_t alpha_t = 0  by
removing one degree of freedom in the parameter vector.

Closed-form derivation of the score function is in
docs/derivations/dixon_coles_mle.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln


@dataclass
class DixonColesFit:
    teams: list[str]
    attack: np.ndarray
    defence: np.ndarray
    home_advantage: float
    rho: float
    log_likelihood: float
    n_matches: int
    converged: bool

    def index(self, team: str) -> int:
        return self.teams.index(team)

    def intensities(self, home: str, away: str) -> tuple[float, float]:
        i = self.index(home)
        j = self.index(away)
        lam = float(np.exp(self.attack[i] + self.defence[j] + self.home_advantage))
        mu = float(np.exp(self.attack[j] + self.defence[i]))
        return lam, mu

    def score_pmf(self, home: str, away: str, max_goals: int = 10) -> np.ndarray:
        lam, mu = self.intensities(home, away)
        x = np.arange(max_goals + 1)
        log_p_home = -lam + x * np.log(lam) - gammaln(x + 1)
        log_p_away = -mu + x * np.log(mu) - gammaln(x + 1)
        pmf = np.exp(log_p_home[:, None] + log_p_away[None, :])
        pmf[0, 0] *= 1 - lam * mu * self.rho
        pmf[0, 1] *= 1 + lam * self.rho
        pmf[1, 0] *= 1 + mu * self.rho
        pmf[1, 1] *= 1 - self.rho
        pmf = np.clip(pmf, 0.0, None)
        pmf /= pmf.sum()
        return pmf

    def outcome_probs(self, home: str, away: str, max_goals: int = 10) -> tuple[float, float, float]:
        pmf = self.score_pmf(home, away, max_goals=max_goals)
        p_home = float(np.tril(pmf, -1).sum())
        p_draw = float(np.trace(pmf))
        p_away = float(np.triu(pmf, 1).sum())
        return p_home, p_draw, p_away


def _tau(x: np.ndarray, y: np.ndarray, lam: np.ndarray, mu: np.ndarray, rho: float) -> np.ndarray:
    out = np.ones_like(lam)
    out = np.where((x == 0) & (y == 0), 1 - lam * mu * rho, out)
    out = np.where((x == 0) & (y == 1), 1 + lam * rho, out)
    out = np.where((x == 1) & (y == 0), 1 + mu * rho, out)
    out = np.where((x == 1) & (y == 1), 1 - rho, out)
    return out


def _log_poisson_pmf(k: np.ndarray, rate: np.ndarray) -> np.ndarray:
    return -rate + k * np.log(rate) - gammaln(k + 1)


def _unpack(theta: np.ndarray, n_teams: int) -> tuple[np.ndarray, np.ndarray, float, float]:
    # alpha has n_teams - 1 free params, sum-to-zero closes the last.
    a_free = theta[: n_teams - 1]
    alpha = np.concatenate([a_free, [-a_free.sum()]])
    beta = theta[n_teams - 1 : 2 * n_teams - 1]
    gamma = float(theta[-2])
    rho = float(theta[-1])
    return alpha, beta, gamma, rho


def _neg_loglik(
    theta: np.ndarray,
    home_idx: np.ndarray,
    away_idx: np.ndarray,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    n_teams: int,
    weights: np.ndarray,
) -> float:
    alpha, beta, gamma, rho = _unpack(theta, n_teams)
    lam = np.exp(alpha[home_idx] + beta[away_idx] + gamma)
    mu = np.exp(alpha[away_idx] + beta[home_idx])
    log_p = _log_poisson_pmf(home_goals, lam) + _log_poisson_pmf(away_goals, mu)
    tau = _tau(home_goals, away_goals, lam, mu, rho)
    if np.any(tau <= 0.0):
        return 1e12
    return float(-np.sum(weights * (np.log(tau) + log_p)))


def fit_dixon_coles(
    *,
    home: list[str],
    away: list[str],
    home_goals: list[int],
    away_goals: list[int],
    xi: float = 0.0,
    match_age_days: list[float] | None = None,
) -> DixonColesFit:
    """Fit by MLE. `xi` is the Dixon-Coles temporal down-weighting rate."""
    if not home:
        raise ValueError("no matches supplied")
    teams = sorted(set(home) | set(away))
    idx = {t: i for i, t in enumerate(teams)}
    n_teams = len(teams)
    home_idx = np.array([idx[t] for t in home])
    away_idx = np.array([idx[t] for t in away])
    hg = np.asarray(home_goals, dtype=float)
    ag = np.asarray(away_goals, dtype=float)

    if match_age_days is not None and xi > 0.0:
        weights = np.exp(-xi * np.asarray(match_age_days, dtype=float))
    else:
        weights = np.ones(len(home), dtype=float)

    theta0 = np.zeros(2 * n_teams + 1)
    theta0[-2] = 0.25  # home advantage warm start
    theta0[-1] = -0.05  # rho warm start

    result = minimize(
        _neg_loglik,
        theta0,
        args=(home_idx, away_idx, hg, ag, n_teams, weights),
        method="L-BFGS-B",
        bounds=[(-3.0, 3.0)] * (2 * n_teams - 1) + [(-1.0, 2.0), (-0.49, 0.49)],
    )

    alpha, beta, gamma, rho = _unpack(result.x, n_teams)
    return DixonColesFit(
        teams=teams,
        attack=alpha,
        defence=beta,
        home_advantage=gamma,
        rho=rho,
        log_likelihood=-float(result.fun),
        n_matches=len(home),
        converged=bool(result.success),
    )
