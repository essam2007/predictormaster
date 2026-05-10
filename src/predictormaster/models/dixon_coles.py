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
        return float(np.inf)
    return float(-np.sum(weights * (np.log(tau) + log_p)))


def _tau_grad(
    x: np.ndarray, y: np.ndarray, lam: np.ndarray, mu: np.ndarray, rho: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (d log tau / d log lam, d log tau / d log mu, d log tau / d rho).

    Using d/d log lam = lam * d/d lam, the chain rule gives (recalling tau = 1
    in non-corner cells, hence zero contribution there):

        cell (0,0): tau = 1 - lam*mu*rho
            d log tau / d log lam = -lam*mu*rho / (1 - lam*mu*rho)
            d log tau / d log mu  = -lam*mu*rho / (1 - lam*mu*rho)
            d log tau / d rho     = -lam*mu     / (1 - lam*mu*rho)
        cell (0,1): tau = 1 + lam*rho
            d log tau / d log lam =  lam*rho   / (1 + lam*rho)
            d log tau / d rho     =  lam       / (1 + lam*rho)
        cell (1,0): tau = 1 + mu*rho
            d log tau / d log mu  =  mu*rho    / (1 + mu*rho)
            d log tau / d rho     =  mu        / (1 + mu*rho)
        cell (1,1): tau = 1 - rho
            d log tau / d rho     = -1         / (1 - rho)
    """
    g_lam = np.zeros_like(lam)
    g_mu = np.zeros_like(lam)
    g_rho = np.zeros_like(lam)

    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)

    if np.any(m00):
        denom = 1.0 - lam[m00] * mu[m00] * rho
        g_lam[m00] = -lam[m00] * mu[m00] * rho / denom
        g_mu[m00] = -lam[m00] * mu[m00] * rho / denom
        g_rho[m00] = -lam[m00] * mu[m00] / denom
    if np.any(m01):
        denom = 1.0 + lam[m01] * rho
        g_lam[m01] = lam[m01] * rho / denom
        g_rho[m01] = lam[m01] / denom
    if np.any(m10):
        denom = 1.0 + mu[m10] * rho
        g_mu[m10] = mu[m10] * rho / denom
        g_rho[m10] = mu[m10] / denom
    if np.any(m11):
        denom = 1.0 - rho
        g_rho[m11] = -1.0 / denom
    return g_lam, g_mu, g_rho


def _neg_loglik_grad(
    theta: np.ndarray,
    home_idx: np.ndarray,
    away_idx: np.ndarray,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    n_teams: int,
    weights: np.ndarray,
) -> np.ndarray:
    """Closed-form gradient of `_neg_loglik` w.r.t. the packed `theta` vector.

    Decomposition (negating because we minimise the negative log-lik):

        d ell / d log lam_i = w_i [ (x_i - lam_i) + g_lam_i ]
        d ell / d log mu_i  = w_i [ (y_i - mu_i)  + g_mu_i  ]
        d ell / d rho       = sum_i w_i * g_rho_i

    Then propagate via:
        log lam_i = alpha_h + beta_a + gamma
        log mu_i  = alpha_a + beta_h

    The sum-to-zero constraint on alpha is enforced by mapping the gradient
    on the n-vector alpha to the (n-1)-vector of free parameters via
        d/d alpha_free_k = d/d alpha_k - d/d alpha_{T-1}.
    """
    alpha, beta, gamma, rho = _unpack(theta, n_teams)
    lam = np.exp(alpha[home_idx] + beta[away_idx] + gamma)
    mu = np.exp(alpha[away_idx] + beta[home_idx])
    tau = _tau(home_goals, away_goals, lam, mu, rho)
    if np.any(tau <= 0.0):
        return np.full_like(theta, np.nan)

    g_lam_tau, g_mu_tau, g_rho_tau = _tau_grad(home_goals, away_goals, lam, mu, rho)
    d_log_lam = weights * ((home_goals - lam) + g_lam_tau)
    d_log_mu = weights * ((away_goals - mu) + g_mu_tau)
    d_rho = float(np.sum(weights * g_rho_tau))

    grad_alpha = np.zeros(n_teams)
    grad_beta = np.zeros(n_teams)
    np.add.at(grad_alpha, home_idx, d_log_lam)
    np.add.at(grad_alpha, away_idx, d_log_mu)
    np.add.at(grad_beta, away_idx, d_log_lam)
    np.add.at(grad_beta, home_idx, d_log_mu)
    grad_gamma = float(np.sum(d_log_lam))

    # alpha_{n-1} = -sum(alpha_free); chain-rule contracts to subtraction.
    grad_alpha_free = grad_alpha[:-1] - grad_alpha[-1]

    grad = np.concatenate([grad_alpha_free, grad_beta, [grad_gamma, d_rho]])
    return -grad  # we minimise -ell; sign-flip the gradient.


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

    # We use unbounded BFGS rather than L-BFGS-B: the alpha/beta/gamma
    # parameters are unbounded in the model (only rho is constrained, and
    # we keep it interior via the inf sentinel inside `_neg_loglik`), and
    # L-BFGS-B's line search interacts badly with the boundary penalty,
    # stalling on iter 1 even with a correct analytic gradient.
    result = minimize(
        _neg_loglik,
        theta0,
        args=(home_idx, away_idx, hg, ag, n_teams, weights),
        jac=_neg_loglik_grad,
        method="BFGS",
        options={"gtol": 1e-5, "maxiter": 200},
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
