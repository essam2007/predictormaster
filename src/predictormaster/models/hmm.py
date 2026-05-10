"""Discrete-emission HMM with Baum-Welch EM.

State at time t: regime z_t in {1..K}.
Observation y_t: index into a finite alphabet of size M.
Used to detect hot/cold streaks and season-long regime arcs.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class HMM:
    pi: np.ndarray  # K
    A: np.ndarray  # K x K transition
    B: np.ndarray  # K x M emission

    @classmethod
    def random(cls, n_states: int, n_obs: int, *, rng: np.random.Generator | None = None) -> "HMM":
        rng = rng or np.random.default_rng(0)
        pi = rng.dirichlet(np.ones(n_states))
        A = rng.dirichlet(np.ones(n_states), size=n_states)
        B = rng.dirichlet(np.ones(n_obs), size=n_states)
        return cls(pi=pi, A=A, B=B)


def _forward(hmm: HMM, obs: np.ndarray) -> tuple[np.ndarray, float]:
    T = len(obs)
    K = len(hmm.pi)
    alpha = np.zeros((T, K))
    scale = np.zeros(T)
    alpha[0] = hmm.pi * hmm.B[:, obs[0]]
    scale[0] = alpha[0].sum()
    alpha[0] /= scale[0]
    for t in range(1, T):
        alpha[t] = (alpha[t - 1] @ hmm.A) * hmm.B[:, obs[t]]
        scale[t] = alpha[t].sum()
        alpha[t] /= scale[t]
    log_lik = float(np.sum(np.log(scale)))
    return alpha, log_lik


def _backward(hmm: HMM, obs: np.ndarray, scale_from_forward: np.ndarray | None = None) -> np.ndarray:
    T = len(obs)
    K = len(hmm.pi)
    beta = np.zeros((T, K))
    beta[-1] = 1.0
    for t in range(T - 2, -1, -1):
        beta[t] = hmm.A @ (hmm.B[:, obs[t + 1]] * beta[t + 1])
        beta[t] /= beta[t].sum() or 1.0
    return beta


def baum_welch(
    obs: np.ndarray,
    n_states: int,
    n_symbols: int,
    *,
    n_iter: int = 50,
    tol: float = 1e-4,
    seed: int = 0,
) -> tuple[HMM, list[float]]:
    rng = np.random.default_rng(seed)
    hmm = HMM.random(n_states, n_symbols, rng=rng)
    history: list[float] = []
    prev_ll = -np.inf
    T = len(obs)
    for _ in range(n_iter):
        alpha, ll = _forward(hmm, obs)
        beta = _backward(hmm, obs)
        gamma = alpha * beta
        gamma /= gamma.sum(axis=1, keepdims=True)
        xi = np.zeros((T - 1, n_states, n_states))
        for t in range(T - 1):
            num = (
                alpha[t][:, None]
                * hmm.A
                * hmm.B[:, obs[t + 1]][None, :]
                * beta[t + 1][None, :]
            )
            xi[t] = num / num.sum()
        hmm.pi = gamma[0]
        hmm.A = xi.sum(axis=0) / gamma[:-1].sum(axis=0)[:, None]
        for s in range(n_symbols):
            mask = obs == s
            hmm.B[:, s] = gamma[mask].sum(axis=0)
        hmm.B /= hmm.B.sum(axis=1, keepdims=True)
        history.append(ll)
        if abs(ll - prev_ll) < tol:
            break
        prev_ll = ll
    return hmm, history


def viterbi(hmm: HMM, obs: np.ndarray) -> np.ndarray:
    T = len(obs)
    K = len(hmm.pi)
    log_pi = np.log(hmm.pi + 1e-12)
    log_A = np.log(hmm.A + 1e-12)
    log_B = np.log(hmm.B + 1e-12)
    delta = np.full((T, K), -np.inf)
    psi = np.zeros((T, K), dtype=int)
    delta[0] = log_pi + log_B[:, obs[0]]
    for t in range(1, T):
        scores = delta[t - 1][:, None] + log_A
        psi[t] = np.argmax(scores, axis=0)
        delta[t] = scores[psi[t], np.arange(K)] + log_B[:, obs[t]]
    path = np.zeros(T, dtype=int)
    path[-1] = int(np.argmax(delta[-1]))
    for t in range(T - 2, -1, -1):
        path[t] = psi[t + 1, path[t + 1]]
    return path
