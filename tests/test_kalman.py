from __future__ import annotations

import numpy as np

from predictormaster.models.kalman import KalmanFilter


def test_kalman_random_walk_converges():
    rng = np.random.default_rng(0)
    truth = 0.0
    F = np.array([[1.0]])
    H = np.array([[1.0]])
    Q = np.array([[0.01]])
    R = np.array([[1.0]])
    kf = KalmanFilter(F=F, H=H, Q=Q, R=R, x=np.zeros(1), P=np.eye(1) * 10)
    estimates = []
    for _ in range(200):
        truth = truth + rng.normal(0, 0.1)
        y = np.array([truth + rng.normal(0, 1.0)])
        kf.step(y)
        estimates.append(float(kf.x[0]))
    final_p = float(kf.P[0, 0])
    assert final_p < 1.0  # uncertainty decreased after many observations
    assert abs(estimates[-1] - truth) < 2.0


def test_kalman_innovation_zero_mean_under_correct_model():
    rng = np.random.default_rng(1)
    F = H = np.eye(1)
    Q = np.array([[0.0]])  # static state
    R = np.array([[1.0]])
    kf = KalmanFilter(F=F, H=H, Q=Q, R=R, x=np.zeros(1), P=np.eye(1) * 4)
    truth = 1.5
    innov = []
    for _ in range(500):
        y = np.array([truth + rng.normal(0, 1.0)])
        kf.predict()
        innov.append(float((y - kf.H @ kf.x).ravel()[0]))
        kf.update(y)
    # Mean of innovation sequence should converge near zero.
    assert abs(np.mean(innov[-200:])) < 0.2
