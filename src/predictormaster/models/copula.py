"""Gaussian copula for cross-player joint dependency.

Pseudo-observations u_i = F_i(x_i) are mapped to z_i = Phi^{-1}(u_i), and the
correlation matrix R is estimated by the maximum-likelihood pseudo-MLE
(Genest, Ghoudi, Rivest 1995). For high-dimensional cases the sparse vine
copula extension is left as a TODO with a documented extension point.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm


@dataclass
class GaussianCopula:
    R: np.ndarray  # d x d correlation matrix

    def sample(self, n: int, *, rng: np.random.Generator | None = None) -> np.ndarray:
        rng = rng or np.random.default_rng()
        L = np.linalg.cholesky(self.R + 1e-9 * np.eye(self.R.shape[0]))
        z = rng.standard_normal((n, self.R.shape[0])) @ L.T
        return norm.cdf(z)


def fit_gaussian_copula(u: np.ndarray) -> GaussianCopula:
    """`u` are pseudo-observations in (0, 1)^{n,d}."""
    eps = 1e-6
    u_clipped = np.clip(u, eps, 1 - eps)
    z = norm.ppf(u_clipped)
    R = np.corrcoef(z, rowvar=False)
    return GaussianCopula(R=R)


def empirical_pseudo_obs(x: np.ndarray) -> np.ndarray:
    n = x.shape[0]
    ranks = np.argsort(np.argsort(x, axis=0), axis=0) + 1
    return ranks / (n + 1)
