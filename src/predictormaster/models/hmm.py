"""Discrete-emission HMM with Baum-Welch EM.

State at time t: regime z_t in {1..K}.
Observation y_t: index into a finite alphabet of size M.
Used to detect hot/cold streaks and season-long regime arcs.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import logsumexp

_TINY = 1e-300


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


def _init_from_obs(obs: np.ndarray, n_states: int, n_obs: int, *, rng: np.random.Generator) -> "HMM":
    """Cheap data-aware init: split `obs` into `n_states` contiguous chunks
    and seed B from the empirical symbol frequency in each chunk. Reduces
    local-optimum variance without any new dependencies.
    """
    pi = rng.dirichlet(np.ones(n_states))
    A = rng.dirichlet(np.ones(n_states) * 5.0, size=n_states)
    B = np.zeros((n_states, n_obs))
    chunks = np.array_split(obs, n_states)
    for k, chunk in enumerate(chunks):
        if len(chunk) == 0:
            B[k] = rng.dirichlet(np.ones(n_obs))
            continue
        counts = np.bincount(chunk, minlength=n_obs).astype(float)
        counts += 1.0  # Laplace smoothing
        B[k] = counts / counts.sum()
    return HMM(pi=pi, A=A, B=B)


def _forward(hmm: HMM, obs: np.ndarray) -> tuple[np.ndarray, float]:
    T = len(obs)
    K = len(hmm.pi)
    alpha = np.zeros((T, K))
    scale = np.zeros(T)
    alpha[0] = hmm.pi * hmm.B[:, obs[0]]
    s0 = alpha[0].sum()
    if s0 < _TINY:
        return _forward_log(hmm, obs)
    scale[0] = s0
    alpha[0] /= s0
    for t in range(1, T):
        alpha[t] = (alpha[t - 1] @ hmm.A) * hmm.B[:, obs[t]]
        s = alpha[t].sum()
        if s < _TINY:
            return _forward_log(hmm, obs)
        scale[t] = s
        alpha[t] /= s
    log_lik = float(np.sum(np.log(scale)))
    return alpha, log_lik


def _forward_log(hmm: HMM, obs: np.ndarray) -> tuple[np.ndarray, float]:
    """Log-space forward as a fallback when the rescaled recursion underflows.

    Returns the same `(alpha_normalised_per_t, log_likelihood)` interface so
    `_forward`'s caller is unchanged.
    """
    T = len(obs)
    K = len(hmm.pi)
    log_pi = np.log(hmm.pi + _TINY)
    log_A = np.log(hmm.A + _TINY)
    log_B = np.log(hmm.B + _TINY)
    log_alpha = np.zeros((T, K))
    log_alpha[0] = log_pi + log_B[:, obs[0]]
    for t in range(1, T):
        log_alpha[t] = logsumexp(log_alpha[t - 1][:, None] + log_A, axis=0) + log_B[:, obs[t]]
    log_lik = float(logsumexp(log_alpha[-1]))
    # Per-t normalised alpha for compatibility with rescaled-form callers.
    alpha = np.exp(log_alpha - logsumexp(log_alpha, axis=1, keepdims=True))
    return alpha, log_lik


def _backward(hmm: HMM, obs: np.ndarray) -> np.ndarray:
    T = len(obs)
    K = len(hmm.pi)
    beta = np.zeros((T, K))
    beta[-1] = 1.0
    for t in range(T - 2, -1, -1):
        beta[t] = hmm.A @ (hmm.B[:, obs[t + 1]] * beta[t + 1])
        s = beta[t].sum()
        if s > _TINY:
            beta[t] /= s
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
    hmm = _init_from_obs(obs, n_states, n_symbols, rng=rng)
    history: list[float] = []
    prev_ll = -np.inf
    T = len(obs)
    for _ in range(n_iter):
        alpha, ll = _forward(hmm, obs)
        beta = _backward(hmm, obs)
        gamma = alpha * beta
        gamma_sum = gamma.sum(axis=1, keepdims=True)
        gamma_sum = np.where(gamma_sum < _TINY, 1.0, gamma_sum)
        gamma = gamma / gamma_sum

        # Vectorised xi: xi[t, k, j] ∝ alpha[t, k] * A[k, j] * B[j, obs[t+1]] * beta[t+1, j]
        emit_next = hmm.B[:, obs[1:]].T  # (T-1, K)
        xi = (
            alpha[:-1, :, None]
            * hmm.A[None, :, :]
            * emit_next[:, None, :]
            * beta[1:, None, :]
        )
        xi_sum = xi.sum(axis=(1, 2), keepdims=True)
        xi_sum = np.where(xi_sum < _TINY, 1.0, xi_sum)
        xi = xi / xi_sum

        hmm.pi = gamma[0]
        denom = gamma[:-1].sum(axis=0)
        denom = np.where(denom < _TINY, 1.0, denom)
        hmm.A = xi.sum(axis=0) / denom[:, None]
        # Renormalise A in case of numerical drift.
        a_row = hmm.A.sum(axis=1, keepdims=True)
        a_row = np.where(a_row < _TINY, 1.0, a_row)
        hmm.A = hmm.A / a_row

        # B update via masked bincount per state.
        for s in range(n_symbols):
            mask = obs == s
            hmm.B[:, s] = gamma[mask].sum(axis=0)
        b_row = hmm.B.sum(axis=1, keepdims=True)
        b_row = np.where(b_row < _TINY, 1.0, b_row)
        hmm.B = hmm.B / b_row

        history.append(ll)
        if abs(ll - prev_ll) < tol:
            break
        prev_ll = ll
    return hmm, history


def viterbi(hmm: HMM, obs: np.ndarray) -> np.ndarray:
    T = len(obs)
    K = len(hmm.pi)
    log_pi = np.log(hmm.pi + _TINY)
    log_A = np.log(hmm.A + _TINY)
    log_B = np.log(hmm.B + _TINY)
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
