"""Bootstrap particle filter for non-Gaussian state-space updating.

The filter is generic in (transition, observation_log_likelihood). We
include systematic resampling to control degeneracy and ESS-based triggering
(Kong, Liu, Wong 1994).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


def systematic_resample(weights: np.ndarray, *, rng: np.random.Generator) -> np.ndarray:
    n = len(weights)
    positions = (np.arange(n) + rng.uniform()) / n
    cum = np.cumsum(weights)
    idx = np.zeros(n, dtype=int)
    i = 0
    j = 0
    while i < n:
        if positions[i] < cum[j]:
            idx[i] = j
            i += 1
        else:
            j += 1
    return idx


@dataclass
class ParticleFilter:
    """Bootstrap particle filter.

    ``resample_threshold`` is the ESS/N ratio at which systematic resampling
    is triggered. Must lie in (0, 1]; the canonical Liu (1996) default is
    0.5. Larger values resample more aggressively (lower variance per step,
    higher Monte Carlo variance over time); smaller values resample less.
    """

    transition: Callable[[np.ndarray, np.random.Generator], np.ndarray]
    log_likelihood: Callable[[np.ndarray, np.ndarray], np.ndarray]
    particles: np.ndarray
    log_weights: np.ndarray
    resample_threshold: float = 0.5

    def __post_init__(self) -> None:
        if not (0.0 < self.resample_threshold <= 1.0):
            raise ValueError(
                f"resample_threshold must lie in (0, 1]; got {self.resample_threshold}"
            )

    def step(self, y: np.ndarray, *, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        self.particles = self.transition(self.particles, rng)
        self.log_weights = self.log_weights + self.log_likelihood(self.particles, y)
        # normalise in log space
        m = float(np.max(self.log_weights))
        w = np.exp(self.log_weights - m)
        w = w / w.sum()
        ess = 1.0 / float(np.sum(w**2))
        if ess / len(w) < self.resample_threshold:
            idx = systematic_resample(w, rng=rng)
            self.particles = self.particles[idx]
            self.log_weights = np.zeros_like(self.log_weights)
            w = np.full_like(w, 1.0 / len(w))
        else:
            self.log_weights = np.log(w)
        return self.particles, w

    def estimate(self) -> tuple[np.ndarray, np.ndarray]:
        m = float(np.max(self.log_weights))
        w = np.exp(self.log_weights - m)
        w = w / w.sum()
        mean = (w[:, None] * self.particles).sum(axis=0) if self.particles.ndim == 2 else float((w * self.particles).sum())
        if self.particles.ndim == 2:
            diff = self.particles - mean
            cov = (w[:, None, None] * (diff[:, :, None] @ diff[:, None, :])).sum(axis=0)
            return mean, cov
        return mean, np.array([(w * (self.particles - mean) ** 2).sum()])
