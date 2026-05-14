"""Composite fitness with the multi-test correction baked in.

The α1 post-mortem showed that any flat Sharpe metric inevitably
discovers selection bias when paired with a search loop. The fitness
here is a *product* of five gates, each ≤ 1:

    fitness = sharpe_norm × dsr × (1 - pbo) × placebo_pass × tx_robust

  - sharpe_norm:    σ(per-bet annualised Sharpe / 2)  ∈ (0, 1)
  - dsr:            Deflated Sharpe vs the running n_trials counter
  - (1 - pbo):      penalty for IS/OOS rank inversion, computed
                    on the *current generation's* variants
  - placebo_pass:   1.0 if 1000× sign-flip p < 0.05, else 0.05
  - tx_robust:      Sharpe(after 2% fee) / Sharpe(no fee), floored at 0

A product means any single failure crushes the candidate — there is
no way to compensate "I scored well on Sharpe but failed placebo" by
brute-forcing the other terms. That asymmetry is on purpose: we want
candidates that pass EVERY honesty check, not ones that average well.

n_trials_so_far is the count of fitness evaluations across the
entire evolution run, not just this generation. DSR scales with it,
so the more genomes we test, the higher the bar each subsequent
genome must clear.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..validation.deflated_sharpe import deflated_sharpe
from ..validation.pbo import pbo as compute_pbo
from .genome import Genome


@dataclass(frozen=True)
class EvaluationResult:
    """One genome's evaluation output. ``per_bet_returns`` is the
    primary diagnostic — composite fitness is derived from it.
    """
    genome: Genome
    per_bet_returns: np.ndarray         # (n_bets,) net of fees
    n_bets: int
    notes: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return self.n_bets < 3


@dataclass(frozen=True)
class FitnessComponents:
    sharpe_per_bet: float               # annualised at bets_per_year
    sharpe_norm: float                  # σ(sr/2)
    dsr: float                          # P(true SR > E[max SR_N])
    pbo: float                          # current-gen probability of overfitting
    placebo_p: float                    # 1000× sign-flip p-value
    placebo_pass: float                 # 1.0 if p<0.05 else 0.05
    tx_robust: float                    # Sharpe(2% fee) / Sharpe(0 fee) clamped to [0,1]
    composite: float                    # the product
    n_bets: int
    n_trials_so_far: int

    def to_dict(self) -> dict:
        return {
            "sharpe_per_bet": self.sharpe_per_bet,
            "sharpe_norm": self.sharpe_norm,
            "dsr": self.dsr,
            "pbo": self.pbo,
            "placebo_p": self.placebo_p,
            "placebo_pass": self.placebo_pass,
            "tx_robust": self.tx_robust,
            "composite": self.composite,
            "n_bets": self.n_bets,
            "n_trials_so_far": self.n_trials_so_far,
        }


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = np.exp(-x)
        return float(1.0 / (1.0 + z))
    z = np.exp(x)
    return float(z / (1.0 + z))


def _per_bet_sharpe_ann(returns: np.ndarray, bets_per_year: int) -> float:
    if returns.size < 3:
        return 0.0
    sd = returns.std(ddof=1)
    if sd <= 0:
        return 0.0
    return float(returns.mean() / sd * np.sqrt(bets_per_year))


def _placebo_p_value(returns: np.ndarray, n_perm: int, rng: np.random.Generator) -> float:
    """Sign-flip permutation test on per-bet annualised Sharpe.

    Reports p = P(|SR_perm| ≥ |SR_obs|) under random sign flips. We
    use absolute value so the test is two-sided — a strategy that
    consistently loses is also "edgy", just on the wrong side, and
    deserves a small p-value too (we then reject it on Sharpe sign).
    """
    if returns.size < 3:
        return 1.0
    sd_obs = returns.std(ddof=1)
    if sd_obs <= 0:
        return 1.0
    sr_obs = abs(returns.mean() / sd_obs)
    count = 0
    n = returns.size
    for _ in range(n_perm):
        signs = rng.choice([-1.0, 1.0], size=n)
        r = returns * signs
        sd = r.std(ddof=1)
        if sd <= 0:
            continue
        sr = abs(r.mean() / sd)
        if sr >= sr_obs:
            count += 1
    return float((count + 1) / (n_perm + 1))   # +1 smoothing avoids p=0


def _tx_cost_robustness(returns: np.ndarray, fee_per_bet: float) -> float:
    """Ratio of Sharpe after subtracting a per-bet fee to Sharpe with
    no fee. Clamped to [0, 1]. Captures how quickly the edge collapses
    once realistic frictions land on each fill."""
    if returns.size < 3:
        return 0.0
    sr0 = _per_bet_sharpe_ann(returns, bets_per_year=200)
    if sr0 <= 0:
        return 0.0
    sr1 = _per_bet_sharpe_ann(returns - fee_per_bet, bets_per_year=200)
    if sr1 <= 0:
        return 0.0
    return float(min(1.0, sr1 / sr0))


def composite_fitness(
    evaluations: list[EvaluationResult],
    *,
    n_trials_so_far: int,
    fee_per_bet: float = 0.02,
    placebo_perms: int = 1000,
    seed: int = 0,
    bets_per_year: int = 200,
) -> list[FitnessComponents]:
    """Compute the composite fitness for every member of a generation.

    PBO is computed once across the entire generation because it
    requires a (T, N) matrix — running it per-genome would be both
    expensive and meaningless. The same PBO value is then applied to
    every genome in the generation, so the term penalises the *family*
    of variants for IS/OOS rank instability, not any single one.
    """
    rng = np.random.default_rng(seed)
    out: list[FitnessComponents] = []

    # ---- PBO across the generation (1 shared value) ----
    pbo_value = 1.0
    valid_returns = [e.per_bet_returns for e in evaluations if not e.is_empty()]
    if len(valid_returns) >= 2:
        # Align on a common index: pad to the max length with zeros so
        # PBO sees comparable variants. Zero-returns contribute no
        # signal but preserve alignment (per pbo.py docstring).
        T = max(r.size for r in valid_returns)
        mat = np.zeros((T, len(valid_returns)))
        for j, r in enumerate(valid_returns):
            mat[: r.size, j] = r
        try:
            pbo_value = float(compute_pbo(mat, n_splits=min(16, T // 2 * 2)).pbo)
        except ValueError:
            pbo_value = 1.0

    # ---- per-genome ----
    for ev in evaluations:
        if ev.is_empty():
            out.append(FitnessComponents(
                sharpe_per_bet=0.0, sharpe_norm=0.0, dsr=0.0, pbo=pbo_value,
                placebo_p=1.0, placebo_pass=0.05, tx_robust=0.0, composite=0.0,
                n_bets=ev.n_bets, n_trials_so_far=n_trials_so_far,
            ))
            continue
        r = ev.per_bet_returns
        sr = _per_bet_sharpe_ann(r, bets_per_year=bets_per_year)
        sharpe_norm = _sigmoid(sr / 2.0)
        dsr_res = deflated_sharpe(r, n_trials=max(1, n_trials_so_far),
                                  periods_per_year=bets_per_year)
        dsr_v = float(dsr_res.dsr)
        # placebo
        p_val = _placebo_p_value(r, placebo_perms, rng)
        placebo_pass = 1.0 if (p_val < 0.05 and sr > 0) else 0.05
        # tx robustness
        tx_r = _tx_cost_robustness(r, fee_per_bet=fee_per_bet)
        composite = sharpe_norm * dsr_v * (1.0 - pbo_value) * placebo_pass * tx_r
        out.append(FitnessComponents(
            sharpe_per_bet=sr,
            sharpe_norm=sharpe_norm,
            dsr=dsr_v,
            pbo=pbo_value,
            placebo_p=p_val,
            placebo_pass=placebo_pass,
            tx_robust=tx_r,
            composite=composite,
            n_bets=ev.n_bets,
            n_trials_so_far=n_trials_so_far,
        ))
    return out
