"""Cox proportional hazards model fit by Breslow's partial-likelihood.

Used for time-to-event modelling: injury recurrence, scoring time in a half,
time-to-substitution. Estimation by Newton-Raphson on the Breslow partial
likelihood; baseline hazard via Breslow estimator.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CoxFit:
    coef: np.ndarray
    cov: np.ndarray
    baseline_times: np.ndarray
    baseline_cum_hazard: np.ndarray
    log_partial_likelihood: float


def fit_cox(
    X: np.ndarray, durations: np.ndarray, events: np.ndarray, *, max_iter: int = 50, tol: float = 1e-6
) -> CoxFit:
    n, p = X.shape
    beta = np.zeros(p)
    order = np.argsort(-durations)  # descending so risk set = prefix
    Xs = X[order]
    ts = durations[order]
    es = events[order]

    for _ in range(max_iter):
        eta = Xs @ beta
        w = np.exp(eta)
        # cumulative sums over the descending-time ordering ≡ risk set sums
        # at each event time when there are no ties. With ties Breslow is
        # used: the loop below segments by tied event times.
        score = np.zeros(p)
        info = np.zeros((p, p))
        log_pl = 0.0
        i = 0
        cum_w = 0.0
        cum_wx = np.zeros(p)
        cum_wxx = np.zeros((p, p))
        while i < n:
            j = i
            while j < n and ts[j] == ts[i]:
                cum_w += w[j]
                cum_wx += w[j] * Xs[j]
                cum_wxx += w[j] * np.outer(Xs[j], Xs[j])
                j += 1
            # all rows in [i, j) share time ts[i]; events among them contribute
            d = int(es[i:j].sum())
            if d > 0 and cum_w > 0:
                xbar = cum_wx / cum_w
                Vmat = cum_wxx / cum_w - np.outer(xbar, xbar)
                ev_rows = Xs[i:j][es[i:j] == 1]
                score += ev_rows.sum(axis=0) - d * xbar
                info += d * Vmat
                log_pl += float(ev_rows.sum(axis=0) @ beta) - d * np.log(cum_w)
            i = j
        try:
            step = np.linalg.solve(info + 1e-8 * np.eye(p), score)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(info, score, rcond=None)[0]
        beta = beta + step
        if np.linalg.norm(step) < tol:
            break

    cov = np.linalg.inv(info + 1e-8 * np.eye(p))
    base_t, base_H = _breslow_baseline(X, durations, events, beta)
    return CoxFit(
        coef=beta,
        cov=cov,
        baseline_times=base_t,
        baseline_cum_hazard=base_H,
        log_partial_likelihood=log_pl,
    )


def _breslow_baseline(
    X: np.ndarray, durations: np.ndarray, events: np.ndarray, beta: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(durations)
    t = durations[order]
    e = events[order]
    risk = np.exp(X[order] @ beta)
    cum_risk = np.cumsum(risk[::-1])[::-1]  # risk set at time t_i is sum_{j: t_j >= t_i}
    times = []
    H = []
    cum = 0.0
    i = 0
    n = len(t)
    while i < n:
        j = i
        while j < n and t[j] == t[i]:
            j += 1
        d = int(e[i:j].sum())
        if d > 0 and cum_risk[i] > 0:
            cum += d / cum_risk[i]
            times.append(t[i])
            H.append(cum)
        i = j
    return np.asarray(times), np.asarray(H)
