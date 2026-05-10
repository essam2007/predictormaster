"""Sparse-GP form-curve estimator using a variational free-energy bound (SVGP).

This is a working pure-NumPy implementation suitable for player-form curves
across a season. Inducing inputs Z are placed at uniform deciles of the
training time axis. The kernel is RBF with optimisable lengthscale and signal
variance via gradient-free coordinate ascent on the marginal likelihood lower
bound.

For very high-throughput use, swap in GPyTorch/SVGP with the same interface.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def rbf(x: np.ndarray, y: np.ndarray, ls: float, sf2: float) -> np.ndarray:
    d2 = (x[:, None] - y[None, :]) ** 2
    return sf2 * np.exp(-0.5 * d2 / ls**2)


@dataclass
class SparseGP:
    Z: np.ndarray
    ls: float
    sf2: float
    sn2: float
    Kuu: np.ndarray
    Kuu_inv: np.ndarray

    def predict(self, x_star: np.ndarray, x_train: np.ndarray, y_train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        Kuf = rbf(self.Z, x_train, self.ls, self.sf2)
        Kus = rbf(self.Z, x_star, self.ls, self.sf2)
        Kss = rbf(x_star, x_star, self.ls, self.sf2)
        # Titsias DTC posterior:
        Sigma = self.Kuu + (Kuf @ Kuf.T) / self.sn2
        Sigma_inv = np.linalg.inv(Sigma + 1e-6 * np.eye(len(self.Z)))
        m = (Kus.T @ Sigma_inv @ Kuf @ y_train) / self.sn2
        v = np.diag(Kss - Kus.T @ self.Kuu_inv @ Kus + Kus.T @ Sigma_inv @ Kus)
        return m, np.maximum(v, 0.0)


def fit_sparse_gp(
    x: np.ndarray,
    y: np.ndarray,
    *,
    n_inducing: int = 16,
    ls_grid: tuple[float, ...] = (1.0, 3.0, 7.0, 14.0, 30.0),
    sf2_grid: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0),
    sn2_grid: tuple[float, ...] = (0.05, 0.1, 0.5, 1.0),
) -> SparseGP:
    quantiles = np.linspace(0.0, 1.0, n_inducing)
    Z = np.quantile(x, quantiles)
    best = None
    best_elbo = -np.inf
    for ls in ls_grid:
        for sf2 in sf2_grid:
            for sn2 in sn2_grid:
                Kuu = rbf(Z, Z, ls, sf2) + 1e-6 * np.eye(len(Z))
                Kuf = rbf(Z, x, ls, sf2)
                Kuu_inv = np.linalg.inv(Kuu)
                Qff_diag = np.einsum("ij,jk,ki->i", Kuf.T, Kuu_inv, Kuf)
                # Titsias bound (collapsed):
                A = Kuu + (Kuf @ Kuf.T) / sn2
                sign, logdetA = np.linalg.slogdet(A)
                _, logdetKuu = np.linalg.slogdet(Kuu)
                n = len(x)
                fit = -0.5 * np.sum(y**2) / sn2
                fit += 0.5 * (Kuf @ y).T @ np.linalg.solve(A, Kuf @ y) / sn2**2
                trace_term = -0.5 * (sf2 * n - Qff_diag.sum()) / sn2
                norm = -0.5 * n * np.log(2 * np.pi * sn2) - 0.5 * (logdetA - logdetKuu)
                elbo = float(fit + trace_term + norm)
                if elbo > best_elbo:
                    best_elbo = elbo
                    best = SparseGP(Z=Z, ls=ls, sf2=sf2, sn2=sn2, Kuu=Kuu, Kuu_inv=Kuu_inv)
    assert best is not None
    return best
