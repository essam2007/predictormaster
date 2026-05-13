"""Hierarchical Risk Parity allocation (López de Prado 2016).

Why HRP, not Markowitz
----------------------
Classical mean-variance optimisation requires inverting Σ. When N
strategies are highly correlated (or sample-noisy at low T), Σ is
near-singular and Σ⁻¹ explodes — Markowitz allocates 200% long /
-100% short on near-identical assets and -200% on a marginal hedge.
That's the source of the well-known "Markowitz curse of dimensionality."

HRP avoids the inversion entirely. It only uses:
  - a distance metric on correlations (always well-defined),
  - agglomerative hierarchical clustering (O(N² log N), deterministic),
  - cluster-variance ratios for capital splits (always positive).

The algorithm
-------------
1. **Distance.** d_ij = √((1 - ρ_ij) / 2) ∈ [0, 1].
   Correlated assets ⇒ small distance ⇒ clustered together.

2. **Linkage.** Single-linkage agglomerative clustering on D yields
   a binary tree where the leaf order is "quasi-diagonal" — assets
   in the same cluster sit next to each other in the reordered Σ.

3. **Quasi-diagonal Σ.** Permute the rows/cols of Σ by leaf order.
   This makes Σ look block-diagonal: tight blocks correspond to
   clusters of correlated strategies.

4. **Recursive bisection.** Walk the cluster tree top-down. At each
   bipartition into clusters C₁, C₂:

       α₁ = 1 - V(C₁) / (V(C₁) + V(C₂))
       α₂ = 1 - α₁

   where V(C) is the *inverse-variance-allocated* variance of
   cluster C — the variance you'd get if you allocated capital
   within C by 1/σᵢ². Multiply each cluster's accumulated weight by
   its α; recurse on each cluster.

This guarantees:
  - All weights are positive (no shorts at the portfolio level).
  - Σ w = 1 (fully invested).
  - Tight clusters share their parent's allocation — no
    over-concentration in a 5-cousins cluster vs. a lone strategy.

Properties under shock
----------------------
The Markowitz failure mode is that during a regime shift, the
historical Σ becomes a *worse* estimate of the realised covariance,
and Σ⁻¹ amplifies the estimation error. HRP, because it never
inverts Σ, degrades gracefully: the cluster structure stays roughly
right (correlations move SLOWLY relative to means), so the allocation
shifts smoothly rather than catastrophically.

For our four-strategy portfolio (α2-arb, α3-sentiment, α4-LOB, plus
any future α5), HRP is over-engineered when N=3 — but the same code
that handles N=3 handles N=30 when we scale, and the cluster diagnostic
("which strategies look alike?") is interpretable in a way that
Markowitz weights never are.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HRPResult:
    """Output of one HRP allocation step."""
    weights: dict[str, float]       # asset → portfolio weight, Σ = 1
    sorted_index: tuple[str, ...]   # quasi-diagonal leaf order
    linkage_matrix: np.ndarray      # scipy linkage Z, shape (N-1, 4)
    correlation_matrix: np.ndarray  # original (N × N) ρ
    distance_matrix: np.ndarray     # √((1 - ρ) / 2)


def correlation_distance(corr: np.ndarray) -> np.ndarray:
    """Map correlation to a proper metric on [0, 1].

    d_ij = √((1 - ρ_ij) / 2). Lipschitz-equivalent to the angular
    distance √2·sin(θ/2) where cos(θ) = ρ.
    """
    return np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))


def _quasi_diag(link: np.ndarray) -> list[int]:
    """Recover the leaf order from a scipy linkage matrix.

    The linkage Z is (N-1) × 4: each row [a, b, dist, n_in_cluster].
    Cluster IDs ≥ N are internal nodes; recursively flatten them.
    Returns the permutation of leaf indices that puts correlated
    leaves adjacent.
    """
    n_leaves = link.shape[0] + 1
    cluster_to_members: dict[int, list[int]] = {}
    for i in range(link.shape[0]):
        cid = n_leaves + i
        left = int(link[i, 0])
        right = int(link[i, 1])
        left_members = (cluster_to_members.pop(left)
                        if left >= n_leaves else [left])
        right_members = (cluster_to_members.pop(right)
                         if right >= n_leaves else [right])
        cluster_to_members[cid] = left_members + right_members
    # The last-created cluster is the root; its members are the full order.
    root = n_leaves + link.shape[0] - 1
    return cluster_to_members[root]


def _cluster_variance(cov: np.ndarray, members: list[int]) -> float:
    """Variance of a cluster under within-cluster inverse-variance allocation.

    For members M, let σ²ᵢ = cov[i,i]. Within-cluster weights are
    wᵢ = (1/σ²ᵢ) / Σ(1/σ²ⱼ). Cluster variance is wᵀ Σ_M w.
    """
    sub = cov[np.ix_(members, members)]
    diag = np.diag(sub)
    inv_var = 1.0 / np.maximum(diag, 1e-12)
    w = inv_var / inv_var.sum()
    return float(w @ sub @ w)


def _recursive_bisect(cov: np.ndarray, sorted_idx: list[int]) -> np.ndarray:
    """Top-down bisection over the quasi-diagonal leaf order."""
    n = cov.shape[0]
    w = np.ones(n)
    # Bisect the *sorted order list* (not the original asset indices)
    # in halves; allocate inversely to cluster variance.
    clusters = [sorted_idx]
    while clusters:
        next_clusters: list[list[int]] = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            mid = len(cluster) // 2
            left, right = cluster[:mid], cluster[mid:]
            v_left = _cluster_variance(cov, left)
            v_right = _cluster_variance(cov, right)
            alpha = 1.0 - v_left / (v_left + v_right + 1e-12)
            # alpha goes to LEFT, (1 - alpha) to RIGHT.
            for idx in left:
                w[idx] *= alpha
            for idx in right:
                w[idx] *= (1.0 - alpha)
            next_clusters.append(left)
            next_clusters.append(right)
        clusters = next_clusters
    return w


def hrp_allocate(returns: np.ndarray, asset_names: list[str] | None = None,
                 *, linkage_method: str = "single") -> HRPResult:
    """Hierarchical Risk Parity allocation.

    Parameters
    ----------
    returns : (T, N) array
        Per-period returns of N strategies/assets.
    asset_names : list of str, optional
        Names matching the N columns. Defaults to ["a0", ..., "a{N-1}"].
    linkage_method : "single" | "average" | "ward" | "complete"
        Which agglomerative method to use. LdP 2016 uses "single";
        "ward" is more robust to outliers but distorts the cluster
        size distribution.

    Returns
    -------
    HRPResult
    """
    from scipy.cluster.hierarchy import linkage
    from scipy.spatial.distance import squareform

    R = np.asarray(returns, dtype=float)
    if R.ndim != 2:
        raise ValueError("returns must be 2-D (T × N)")
    T, N = R.shape
    if N < 2:
        # Trivial 1-asset case.
        names = asset_names or [f"a{i}" for i in range(N)]
        return HRPResult(
            weights={names[0]: 1.0} if N == 1 else {},
            sorted_index=tuple(names),
            linkage_matrix=np.zeros((0, 4)),
            correlation_matrix=np.ones((N, N)),
            distance_matrix=np.zeros((N, N)),
        )
    if T < 3:
        raise ValueError("need ≥3 periods to estimate Σ")

    names = asset_names or [f"a{i}" for i in range(N)]
    if len(names) != N:
        raise ValueError(f"asset_names length {len(names)} ≠ N={N}")

    # Sample covariance / correlation. ddof=1 for unbiased σ̂².
    cov = np.cov(R, rowvar=False, ddof=1)
    sd = np.sqrt(np.diag(cov))
    sd_safe = np.where(sd > 0, sd, 1.0)
    corr = cov / np.outer(sd_safe, sd_safe)
    corr = np.clip(corr, -1.0, 1.0)

    dist = correlation_distance(corr)
    # scipy expects condensed distance vector.
    cond = squareform(dist, checks=False)
    link = linkage(cond, method=linkage_method)

    sorted_idx = _quasi_diag(link)
    raw_w = _recursive_bisect(cov, sorted_idx)
    # Normalise (recursive bisection already gives Σw = 1 modulo
    # numerical drift; re-normalise to be safe).
    raw_w = raw_w / raw_w.sum()

    weights = {names[i]: float(raw_w[i]) for i in range(N)}
    return HRPResult(
        weights=weights,
        sorted_index=tuple(names[i] for i in sorted_idx),
        linkage_matrix=link,
        correlation_matrix=corr,
        distance_matrix=dist,
    )


# ---------------- Diagnostics & comparison ----------------

@dataclass(frozen=True)
class PortfolioMetrics:
    """Compares competing allocations on a held-out return series."""
    name: str
    annual_sharpe: float
    annual_return: float
    annual_vol: float
    max_drawdown: float
    weight_concentration: float    # Σwᵢ² (Herfindahl) — 1/N is perfectly diversified


def evaluate_weights(returns: np.ndarray, weights: dict[str, float],
                     asset_names: list[str],
                     *, periods_per_year: int = 252,
                     name: str = "portfolio") -> PortfolioMetrics:
    """Run a portfolio with constant ``weights`` against ``returns``.

    The point of this helper is post-hoc comparison: HRP vs.
    equal-weight vs. inverse-vol vs. Markowitz. Same return matrix
    plugs into all four.
    """
    R = np.asarray(returns, dtype=float)
    w = np.array([weights.get(n, 0.0) for n in asset_names], dtype=float)
    port_rets = R @ w
    mu = float(port_rets.mean())
    sd = float(port_rets.std(ddof=1))
    sr = mu / sd * np.sqrt(periods_per_year) if sd > 0 else 0.0
    eq = (1.0 + port_rets).cumprod()
    dd = float((eq / np.maximum.accumulate(eq) - 1.0).min()) if len(eq) > 0 else 0.0
    hhi = float((w * w).sum())
    return PortfolioMetrics(
        name=name,
        annual_sharpe=float(sr),
        annual_return=float(mu * periods_per_year),
        annual_vol=float(sd * np.sqrt(periods_per_year)),
        max_drawdown=dd,
        weight_concentration=hhi,
    )


def equal_weight(asset_names: list[str]) -> dict[str, float]:
    n = len(asset_names)
    return {a: 1.0 / n for a in asset_names} if n else {}


def inverse_volatility(returns: np.ndarray, asset_names: list[str]) -> dict[str, float]:
    """Naive baseline: wᵢ ∝ 1/σᵢ, normalised. Doesn't use correlations."""
    sd = np.std(returns, axis=0, ddof=1)
    inv = 1.0 / np.maximum(sd, 1e-12)
    inv = inv / inv.sum()
    return {asset_names[i]: float(inv[i]) for i in range(len(asset_names))}
