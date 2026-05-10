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


def _bin_indices(probs: np.ndarray, n_bins: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    bins = np.clip(np.digitize(probs, edges[1:-1], right=False), 0, n_bins - 1)
    return bins, edges, centers


def expected_calibration_error(
    probs: np.ndarray, labels: np.ndarray, *, n_bins: int = 15
) -> CalibrationReport:
    """For binary probabilities `probs` against {0,1} `labels`."""
    probs = np.asarray(probs, dtype=float)
    labels = np.asarray(labels, dtype=int)
    if probs.ndim != 1:
        raise ValueError("probs must be 1-D for binary ECE")
    n = len(probs)
    bins, _, centers = _bin_indices(probs, n_bins)
    counts = np.bincount(bins, minlength=n_bins)
    sum_probs = np.bincount(bins, weights=probs, minlength=n_bins)
    sum_labels = np.bincount(bins, weights=labels.astype(float), minlength=n_bins)
    nz = counts > 0
    confidences = np.zeros(n_bins)
    accuracies = np.zeros(n_bins)
    confidences[nz] = sum_probs[nz] / counts[nz]
    accuracies[nz] = sum_labels[nz] / counts[nz]
    weights = counts / max(n, 1)
    ece = float(np.sum(weights * np.abs(confidences - accuracies)))
    diffs = np.abs(confidences[nz] - accuracies[nz])
    mce = float(diffs.max()) if diffs.size else 0.0
    rel, res, unc = brier_decomposition(probs, labels, n_bins=n_bins)
    brier = float(np.mean((probs - labels) ** 2))
    return CalibrationReport(
        ece=ece,
        mce=mce,
        bin_centers=centers,
        bin_confidences=confidences,
        bin_accuracies=accuracies,
        bin_counts=counts.astype(int),
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
    n = len(probs)
    o_bar = float(labels.mean())
    bins, _, _ = _bin_indices(probs, n_bins)
    counts = np.bincount(bins, minlength=n_bins)
    sum_probs = np.bincount(bins, weights=probs, minlength=n_bins)
    sum_labels = np.bincount(bins, weights=labels.astype(float), minlength=n_bins)
    nz = counts > 0
    f_bar = np.zeros(n_bins)
    o_bar_k = np.zeros(n_bins)
    f_bar[nz] = sum_probs[nz] / counts[nz]
    o_bar_k[nz] = sum_labels[nz] / counts[nz]
    rel = float(np.sum(counts * (f_bar - o_bar_k) ** 2) / max(n, 1))
    res = float(np.sum(counts * (o_bar_k - o_bar) ** 2) / max(n, 1))
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


# ----- Multi-class calibration ------------------------------------------------


def top_label_ece(probs2d: np.ndarray, labels: np.ndarray, *, n_bins: int = 15) -> float:
    """ECE on the top-predicted class (Guo et al. 2017)."""
    probs2d = np.asarray(probs2d, dtype=float)
    labels = np.asarray(labels, dtype=int)
    if probs2d.ndim != 2:
        raise ValueError("probs2d must be (n, K)")
    confidence = probs2d.max(axis=1)
    predicted = probs2d.argmax(axis=1)
    correct = (predicted == labels).astype(float)
    return expected_calibration_error(confidence, correct, n_bins=n_bins).ece


def class_wise_ece(
    probs2d: np.ndarray, labels: np.ndarray, *, n_bins: int = 15
) -> dict[int, float]:
    """Per-class ECE: for each class k, treat probs[:, k] as P(Y = k) and
    1{labels == k} as the binary label. Reports {k: ece_k}.
    """
    probs2d = np.asarray(probs2d, dtype=float)
    labels = np.asarray(labels, dtype=int)
    K = probs2d.shape[1]
    out: dict[int, float] = {}
    for k in range(K):
        rep = expected_calibration_error(
            probs2d[:, k], (labels == k).astype(int), n_bins=n_bins
        )
        out[k] = rep.ece
    return out


def brier_multiclass(probs2d: np.ndarray, labels: np.ndarray) -> float:
    """Multi-class Brier: mean over rows of sum_k (p_k - 1{y=k})^2.

    Reduces to twice the binary Brier score when K=2, which is the standard
    convention; consumers comparing against the binary value should divide
    by 2 if needed.
    """
    probs2d = np.asarray(probs2d, dtype=float)
    labels = np.asarray(labels, dtype=int)
    K = probs2d.shape[1]
    onehot = np.eye(K)[labels]
    return float(np.mean(np.sum((probs2d - onehot) ** 2, axis=1)))
