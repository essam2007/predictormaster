"""Linear-Gaussian Kalman filter for latent team-strength tracking.

State model
    x_{t+1} = F x_t + w_t,    w_t ~ N(0, Q)
Observation
    y_t     = H x_t + v_t,    v_t ~ N(0, R)

Closed-form predict / update derived in docs/derivations/kalman_filter.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class KalmanFilter:
    F: np.ndarray  # n x n
    H: np.ndarray  # m x n
    Q: np.ndarray  # n x n
    R: np.ndarray  # m x m
    x: np.ndarray  # n
    P: np.ndarray  # n x n

    def predict(self) -> tuple[np.ndarray, np.ndarray]:
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x.copy(), self.P.copy()

    def update(self, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        innov = y - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ innov
        eye = np.eye(self.P.shape[0])
        self.P = (eye - K @ self.H) @ self.P
        return self.x.copy(), self.P.copy()

    def step(self, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self.predict()
        return self.update(y)


def team_strength_filter(n_teams: int, *, q: float = 0.01, r: float = 0.5) -> KalmanFilter:
    """Build a random-walk strength filter where each team has its own latent
    state and observation = own strength minus opponent strength + noise.
    """
    F = np.eye(n_teams)
    H = np.eye(n_teams)
    Q = q * np.eye(n_teams)
    R = r * np.eye(n_teams)
    x = np.zeros(n_teams)
    P = np.eye(n_teams)
    return KalmanFilter(F=F, H=H, Q=Q, R=R, x=x, P=P)
