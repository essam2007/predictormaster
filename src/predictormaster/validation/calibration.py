"""Calibration metrics: ECE, MCE, reliability diagrams, Brier decomposition.

Murphy's decomposition is derived in docs/derivations/brier_decomposition.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CalibrationReport:
    ece: float
    mce: float
    bin_centers: np.ndarray
    bin_confidences: np.ndarray
    bin_accuracies: np.ndarray
    bin_counts: np.ndarray
    reliability: float
    resolution: float
    uncertainty: float
    brier: float


def expected_calibration_error(
    probs: np.ndarray, labels: np.ndarray, *, n_bins: int = 15
) -> CalibrationReport:
    """For binary probabilities `probs` against {0,1} `labels`."""
    probs = np.asarray(probs, dtype=float)
    labels = np.asarray(labels, dtype=int)
    if probs.ndim != 1:
        raise ValueError("probs must be 1-D for binary ECE")
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    confidences = np.zeros(n_bins)
    accuracies = np.zeros(n_bins)
    counts = np.zeros(n_bins, dtype=int)
    n = len(probs)
    for k in range(n_bins):
        mask = (probs >= edges[k]) & (probs < edges[k + 1] if k < n_bins - 1 else probs <= edges[k + 1])
        if not mask.any():
            continue
        confidences[k] = float(probs[mask].mean())
        accuracies[k] = float(labels[mask].mean())
        counts[k] = int(mask.sum())
    weights = counts / max(n, 1)
    ece = float(np.sum(weights * np.abs(confidences - accuracies)))
    mce = float(np.max(np.abs(confidences - accuracies)))
    rel, res, unc = brier_decomposition(probs, labels, n_bins=n_bins)
    brier = float(np.mean((probs - labels) ** 2))
    return CalibrationReport(
        ece=ece,
        mce=mce,
        bin_centers=centers,
        bin_confidences=confidences,
        bin_accuracies=accuracies,
        bin_counts=counts,
        reliability=rel,
        resolution=res,
        uncertainty=unc,
        brier=brier,
    )


def brier_decomposition(
    probs: np.ndarray, labels: np.ndarray, *, n_bins: int = 15
) -> tuple[float, float, float]:
    """Murphy: BS = REL - RES + UNC."""
    probs = np.asarray(probs, dtype=float)
    labels = np.asarray(labels, dtype=int)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    n = len(probs)
    o_bar = float(labels.mean())
    rel = 0.0
    res = 0.0
    for k in range(n_bins):
        mask = (probs >= edges[k]) & (probs < edges[k + 1] if k < n_bins - 1 else probs <= edges[k + 1])
        nk = int(mask.sum())
        if nk == 0:
            continue
        f_bar_k = float(probs[mask].mean())
        o_bar_k = float(labels[mask].mean())
        rel += nk * (f_bar_k - o_bar_k) ** 2
        res += nk * (o_bar_k - o_bar) ** 2
    rel /= n
    res /= n
    unc = o_bar * (1 - o_bar)
    return rel, res, unc


def brier_skill_score(probs: np.ndarray, labels: np.ndarray, baseline_probs: np.ndarray) -> float:
    bs = float(np.mean((probs - labels) ** 2))
    bs_ref = float(np.mean((baseline_probs - labels) ** 2))
    if bs_ref == 0:
        return 0.0
    return 1.0 - bs / bs_ref


def log_loss(probs: np.ndarray, labels: np.ndarray, eps: float = 1e-12) -> float:
    """Binary or multiclass log-loss. `probs` shape (n,) or (n, K)."""
    probs = np.clip(probs, eps, 1 - eps)
    if probs.ndim == 1:
        return float(-np.mean(labels * np.log(probs) + (1 - labels) * np.log(1 - probs)))
    n = probs.shape[0]
    return float(-np.mean(np.log(probs[np.arange(n), labels])))
