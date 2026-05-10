"""Market-efficiency research toolkit.

Implements:

* event-study cumulative-abnormal-return analysis on consensus probability
  trajectories around information-arrival events,
* fixed-effects panel regression with HC3 robust standard errors,
* Benjamini-Hochberg FDR control,
* entropy of the cross-platform consensus distribution as a disagreement
  measure.

All functions are NumPy/SciPy native — statsmodels is optional.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass
class EventStudyResult:
    window: tuple[int, int]
    car: np.ndarray  # cumulative abnormal returns
    aar: np.ndarray  # average abnormal returns by event-time
    t_stats: np.ndarray
    p_values: np.ndarray


def event_study(
    *,
    series: np.ndarray,  # n_events x T
    event_index: int,
    pre: int,
    post: int,
    expected: np.ndarray | None = None,
) -> EventStudyResult:
    """Aggregate abnormal moves around `event_index` over a [pre, post] window."""
    n, T = series.shape
    lo = event_index - pre
    hi = event_index + post + 1
    if lo < 0 or hi > T:
        raise ValueError("event window out of bounds")
    window = series[:, lo:hi]
    if expected is None:
        expected = series[:, :lo].mean(axis=1, keepdims=True)
    abnormal = window - expected
    aar = abnormal.mean(axis=0)
    car = np.cumsum(aar)
    se = abnormal.std(axis=0, ddof=1) / np.sqrt(n)
    t = np.divide(aar, se, out=np.zeros_like(aar), where=se > 0)
    p = 2.0 * (1.0 - stats.t.cdf(np.abs(t), df=max(n - 1, 1)))
    return EventStudyResult(window=(-pre, post), car=car, aar=aar, t_stats=t, p_values=p)


@dataclass
class PanelOLS:
    coef: np.ndarray
    se_hc3: np.ndarray
    t: np.ndarray
    p: np.ndarray
    feature_names: list[str]
    r2: float
    n: int


def panel_regression_hc3(
    X: np.ndarray, y: np.ndarray, *, fixed_effects: np.ndarray | None = None, feature_names: list[str] | None = None
) -> PanelOLS:
    """OLS with HC3 robust SEs and demeaned fixed effects."""
    feature_names = feature_names or [f"x{i}" for i in range(X.shape[1])]
    Xd = X.copy().astype(float)
    yd = y.copy().astype(float)
    if fixed_effects is not None:
        groups, inv = np.unique(fixed_effects, return_inverse=True)
        for g_idx in range(len(groups)):
            m = inv == g_idx
            Xd[m] -= Xd[m].mean(axis=0)
            yd[m] -= yd[m].mean()
    Xd = np.hstack([np.ones((Xd.shape[0], 1)), Xd])
    feature_names = ["intercept", *feature_names]
    XtX_inv = np.linalg.inv(Xd.T @ Xd)
    beta = XtX_inv @ Xd.T @ yd
    resid = yd - Xd @ beta
    h = np.einsum("ij,jk,ik->i", Xd, XtX_inv, Xd)
    h = np.clip(h, 0, 0.999)
    omega = (resid / (1 - h)) ** 2
    S = (Xd.T * omega) @ Xd
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    t_stats = beta / np.where(se > 0, se, 1.0)
    df = max(len(yd) - len(beta), 1)
    p = 2.0 * (1.0 - stats.t.cdf(np.abs(t_stats), df=df))
    ss_res = float((resid**2).sum())
    ss_tot = float(((yd - yd.mean()) ** 2).sum()) or 1.0
    r2 = 1.0 - ss_res / ss_tot
    return PanelOLS(
        coef=beta, se_hc3=se, t=t_stats, p=p, feature_names=feature_names, r2=r2, n=len(yd)
    )


def benjamini_hochberg(pvals: np.ndarray, alpha: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Return (rejected, q-values) under BH(alpha)."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * n / (np.arange(n) + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q_full = np.empty(n)
    q_full[order] = q
    rejected = q_full <= alpha
    return rejected, q_full


def consensus_entropy(probs_by_source: np.ndarray) -> float:
    """Cross-source disagreement: entropy of the *mean* distribution.

    `probs_by_source` is shape (S, K). Returns a scalar in nats.
    """
    p = probs_by_source.mean(axis=0)
    p = p / p.sum()
    return float(-np.sum(p * np.log(p + 1e-12)))


def information_incorporation_speed(
    *, abnormal_series: np.ndarray, threshold: float = 0.05
) -> int:
    """Steps post-event before |abnormal| stabilises below threshold."""
    for i, x in enumerate(abnormal_series):
        if abs(x) < threshold:
            return i
    return len(abnormal_series)
