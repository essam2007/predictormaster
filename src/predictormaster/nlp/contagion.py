"""Emotional contagion model on a social graph.

A discrete-time SIR-like diffusion: nodes carry a continuous sentiment
state s in [-1, 1], with transmission rate beta along edges and decay
gamma towards baseline. Used to predict propagation of narrative shocks
(injury news, lineup changes) through a network.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ContagionResult:
    states: np.ndarray  # T x N
    final: np.ndarray
    peak_step: int


def simulate_contagion(
    *,
    adjacency: np.ndarray,
    initial_state: np.ndarray,
    beta: float = 0.15,
    gamma: float = 0.05,
    steps: int = 30,
) -> ContagionResult:
    n = adjacency.shape[0]
    deg = adjacency.sum(axis=1)
    deg[deg == 0] = 1.0
    P = adjacency / deg[:, None]
    s = initial_state.astype(float).copy()
    history = np.zeros((steps + 1, n))
    history[0] = s
    energy = np.abs(s).sum()
    peak_step = 0
    peak_energy = energy
    for t in range(1, steps + 1):
        neighbour_avg = P @ s
        s = (1 - gamma) * s + beta * (neighbour_avg - s)
        s = np.clip(s, -1.0, 1.0)
        history[t] = s
        e = float(np.abs(s).sum())
        if e > peak_energy:
            peak_energy = e
            peak_step = t
    return ContagionResult(states=history, final=s, peak_step=peak_step)
