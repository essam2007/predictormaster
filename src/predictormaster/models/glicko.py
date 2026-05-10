"""Glicko-2 rating system (Glickman 2012).

Implements the canonical scale-converted update with iterative volatility
solve. Constants follow the original paper:

    tau    : volatility prior (system parameter), default 0.5
    epsilon: convergence tolerance for the volatility iteration

A rating period batches all results since the last `update`. For "online"
play, call `update` with each match in its own period and pass tau small.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

_SCALE = 173.7178


@dataclass
class GlickoState:
    rating: float = 1500.0
    rd: float = 350.0
    sigma: float = 0.06


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi**2 / math.pi**2)


def _e(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def _solve_volatility(sigma: float, phi: float, v: float, delta: float, tau: float, eps: float = 1e-6) -> float:
    a = math.log(sigma**2)

    def f(x: float) -> float:
        ex = math.exp(x)
        num = ex * (delta**2 - phi**2 - v - ex)
        den = 2.0 * (phi**2 + v + ex) ** 2
        return num / den - (x - a) / tau**2

    A = a
    if delta**2 > phi**2 + v:
        B = math.log(delta**2 - phi**2 - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        B = a - k * tau
    fa, fb = f(A), f(B)
    while abs(B - A) > eps:
        C = A + (A - B) * fa / (fb - fa)
        fc = f(C)
        if fc * fb <= 0:
            A, fa = B, fb
        else:
            fa = fa / 2.0
        B, fb = C, fc
    return math.exp(A / 2.0)


@dataclass
class Glicko2:
    tau: float = 0.5
    states: dict[str, GlickoState] = field(default_factory=dict)

    def state(self, player: str) -> GlickoState:
        return self.states.setdefault(player, GlickoState())

    def update(self, player: str, results: list[tuple[str, float]]) -> GlickoState:
        """Apply a single rating period for `player` against opponents.

        results: list of (opponent_id, score in {0, 0.5, 1}).
        """
        st = self.state(player)
        mu = (st.rating - 1500.0) / _SCALE
        phi = st.rd / _SCALE

        if not results:
            phi_new = math.sqrt(phi**2 + st.sigma**2)
            st.rd = phi_new * _SCALE
            return st

        v_inv = 0.0
        delta_sum = 0.0
        for opp, s in results:
            ost = self.state(opp)
            mu_j = (ost.rating - 1500.0) / _SCALE
            phi_j = ost.rd / _SCALE
            g = _g(phi_j)
            e = _e(mu, mu_j, phi_j)
            v_inv += g * g * e * (1 - e)
            delta_sum += g * (s - e)
        v = 1.0 / v_inv
        delta = v * delta_sum

        sigma_new = _solve_volatility(st.sigma, phi, v, delta, self.tau)
        phi_star = math.sqrt(phi**2 + sigma_new**2)
        phi_new = 1.0 / math.sqrt(1.0 / phi_star**2 + 1.0 / v)
        mu_new = mu + phi_new**2 * delta_sum

        st.rating = 1500.0 + _SCALE * mu_new
        st.rd = _SCALE * phi_new
        st.sigma = sigma_new
        return st
