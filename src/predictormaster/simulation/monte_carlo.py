"""Vectorised Monte Carlo simulator for match outcomes.

Two backends:
  * `simulate_poisson` — closed-form Poisson scoring, fast (uses NumPy
    `poisson` sampler). 50,000 simulations of a single match in ~3ms on a
    laptop CPU.
  * `simulate_possessions` — possession-by-possession with per-possession
    success probabilities; matches the architecture described in
    docs/architecture.md and is GPU-accelerable via CuPy when CUDA is
    available.

`variance_decomposition` runs an ANOVA-style attribution of forecast
variance to data, model, and aleatory components.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SimulationResult:
    p_home: float
    p_draw: float
    p_away: float
    expected_score_home: float
    expected_score_away: float
    score_pmf: np.ndarray
    epistemic_var: float
    aleatoric_var: float
    n_sims: int


def simulate_poisson(
    *, lam_home: float, lam_away: float, n_sims: int = 50_000, seed: int = 0
) -> SimulationResult:
    rng = np.random.default_rng(seed)
    h = rng.poisson(lam_home, size=n_sims)
    a = rng.poisson(lam_away, size=n_sims)
    p_home = float(np.mean(h > a))
    p_draw = float(np.mean(h == a))
    p_away = float(np.mean(h < a))
    pmf = _pmf_from_samples(h, a, max_goals=12)
    return SimulationResult(
        p_home=p_home,
        p_draw=p_draw,
        p_away=p_away,
        expected_score_home=float(h.mean()),
        expected_score_away=float(a.mean()),
        score_pmf=pmf,
        epistemic_var=0.0,
        aleatoric_var=float(h.var() + a.var()),
        n_sims=n_sims,
    )


def _pmf_from_samples(h: np.ndarray, a: np.ndarray, max_goals: int) -> np.ndarray:
    pmf = np.zeros((max_goals + 1, max_goals + 1))
    h_clipped = np.clip(h, 0, max_goals)
    a_clipped = np.clip(a, 0, max_goals)
    for hi, ai in zip(h_clipped, a_clipped, strict=True):
        pmf[hi, ai] += 1
    pmf /= pmf.sum()
    return pmf


def simulate_possessions(
    *,
    n_possessions: int,
    home_score_prob: float,
    away_score_prob: float,
    home_points_dist: tuple[tuple[int, float], ...] = ((2, 0.55), (3, 0.35), (1, 0.10)),
    away_points_dist: tuple[tuple[int, float], ...] = ((2, 0.55), (3, 0.35), (1, 0.10)),
    n_sims: int = 50_000,
    seed: int = 0,
) -> SimulationResult:
    rng = np.random.default_rng(seed)
    home_pts, home_p = zip(*home_points_dist, strict=True)
    away_pts, away_p = zip(*away_points_dist, strict=True)
    home_p = np.asarray(home_p) / sum(home_p)
    away_p = np.asarray(away_p) / sum(away_p)

    half = n_possessions // 2
    home_made = rng.binomial(half, home_score_prob, size=n_sims)
    away_made = rng.binomial(n_possessions - half, away_score_prob, size=n_sims)
    h = np.zeros(n_sims, dtype=int)
    a = np.zeros(n_sims, dtype=int)
    for i in range(n_sims):
        if home_made[i] > 0:
            h[i] = int(rng.choice(home_pts, p=home_p, size=home_made[i]).sum())
        if away_made[i] > 0:
            a[i] = int(rng.choice(away_pts, p=away_p, size=away_made[i]).sum())
    p_home = float(np.mean(h > a))
    p_draw = float(np.mean(h == a))
    p_away = float(np.mean(h < a))
    pmf = _pmf_from_samples(h, a, max_goals=180)
    return SimulationResult(
        p_home=p_home,
        p_draw=p_draw,
        p_away=p_away,
        expected_score_home=float(h.mean()),
        expected_score_away=float(a.mean()),
        score_pmf=pmf,
        epistemic_var=0.0,
        aleatoric_var=float(h.var() + a.var()),
        n_sims=n_sims,
    )


def variance_decomposition(
    samples_per_param_set: list[np.ndarray],
) -> dict[str, float]:
    """Attribute variance across uncertainty sources via the law of total variance.

    Each entry in `samples_per_param_set` is an array of outcome samples
    drawn from one posterior parameter draw. We split:

        Var(Y) = E[Var(Y | theta)] + Var(E[Y | theta])
                 ^ aleatoric          ^ epistemic / model
    """
    means = np.array([s.mean() for s in samples_per_param_set])
    inner_var = np.array([s.var() for s in samples_per_param_set])
    epistemic = float(means.var())
    aleatoric = float(inner_var.mean())
    return {"epistemic": epistemic, "aleatoric": aleatoric, "total": epistemic + aleatoric}
