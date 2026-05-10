"""Information-theoretic feature scoring."""
from __future__ import annotations

import numpy as np


def entropy(p: np.ndarray, eps: float = 1e-12) -> float:
    p = np.clip(p, eps, 1.0)
    return float(-np.sum(p * np.log(p)))


def joint_histogram(x: np.ndarray, y: np.ndarray, bins: int = 16) -> np.ndarray:
    h, _, _ = np.histogram2d(x, y, bins=bins)
    return h / max(h.sum(), 1.0)


def mutual_information(x: np.ndarray, y: np.ndarray, bins: int = 16) -> float:
    pxy = joint_histogram(x, y, bins)
    px = pxy.sum(axis=1)
    py = pxy.sum(axis=0)
    nz = pxy > 0
    log_ratio = np.zeros_like(pxy)
    log_ratio[nz] = np.log(pxy[nz] / (px[:, None] * py[None, :])[nz] + 1e-12)
    return float(np.sum(pxy * log_ratio))


def population_stability_index(p: np.ndarray, q: np.ndarray, eps: float = 1e-6) -> float:
    p = np.clip(p, eps, None)
    q = np.clip(q, eps, None)
    p = p / p.sum()
    q = q / q.sum()
    return float(np.sum((p - q) * np.log(p / q)))


def kl_divergence(p: np.ndarray, q: np.ndarray, eps: float = 1e-12) -> float:
    p = np.clip(p, eps, 1.0)
    q = np.clip(q, eps, 1.0)
    return float(np.sum(p * np.log(p / q)))
