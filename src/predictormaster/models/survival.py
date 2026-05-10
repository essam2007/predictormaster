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
    # Sort descending so risk-set sums are a forward cumsum.
    order = np.argsort(-durations)
    Xs = X[order]
    ts = durations[order]
    es = events[order]

    # Pre-compute tied-time segmentation once. `seg_starts[k]` = first row index
    # of segment k; rows in [seg_starts[k], seg_starts[k+1]) all share ts value.
    # `np.unique` returns ascending; flip to match the descending sort.
    _, first_idx = np.unique(ts[::-1], return_index=True)
    seg_ends = n - first_idx  # one past the last row of each (descending) segment
    seg_ends = np.sort(seg_ends)
    seg_starts = np.concatenate([[0], seg_ends[:-1]])

    n_segs = len(seg_starts)

    for _ in range(max_iter):
        eta = Xs @ beta
        w = np.exp(eta)
        # Per-segment aggregations via reduceat: each segment gets w-sum,
        # wx-sum, wxx-sum across its rows; cumulative sums over segments give
        # the prefix-up-to-segment-end risk-set quantities used by Breslow.
        seg_w = np.add.reduceat(w, seg_starts)
        seg_wx = np.add.reduceat(w[:, None] * Xs, seg_starts, axis=0)
        # wxx is (n, p, p); reduceat along axis 0:
        wxx = w[:, None, None] * (Xs[:, :, None] * Xs[:, None, :])
        seg_wxx = np.add.reduceat(wxx, seg_starts, axis=0)

        cum_w = np.cumsum(seg_w)
        cum_wx = np.cumsum(seg_wx, axis=0)
        cum_wxx = np.cumsum(seg_wxx, axis=0)

        score = np.zeros(p)
        info = np.zeros((p, p))
        log_pl = 0.0
        for k in range(n_segs):
            i, j = seg_starts[k], seg_ends[k]
            d = int(es[i:j].sum())
            if d == 0 or cum_w[k] <= 0:
                continue
            xbar = cum_wx[k] / cum_w[k]
            Vmat = cum_wxx[k] / cum_w[k] - np.outer(xbar, xbar)
            ev_rows = Xs[i:j][es[i:j] == 1]
            score += ev_rows.sum(axis=0) - d * xbar
            info += d * Vmat
            log_pl += float(ev_rows.sum(axis=0) @ beta) - d * np.log(cum_w[k])

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
