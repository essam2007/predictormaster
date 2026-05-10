from __future__ import annotations

import numpy as np

from predictormaster.market.efficiency import (
    benjamini_hochberg,
    consensus_entropy,
    event_study,
    panel_regression_hc3,
)


def test_event_study_detects_jump():
    rng = np.random.default_rng(0)
    n_events, T = 200, 30
    series = rng.normal(0.0, 0.1, size=(n_events, T))
    series[:, 15:] += 0.5  # event at t=15
    res = event_study(series=series, event_index=15, pre=5, post=10)
    assert res.car[-1] > 0.5


def test_panel_regression_recovers_signal():
    rng = np.random.default_rng(1)
    n = 1000
    fe = rng.integers(0, 10, size=n)
    x = rng.normal(0, 1, size=(n, 2))
    fe_offsets = rng.normal(0, 1, size=10)
    y = 0.5 * x[:, 0] - 0.3 * x[:, 1] + fe_offsets[fe] + rng.normal(0, 0.1, size=n)
    fit = panel_regression_hc3(x, y, fixed_effects=fe, feature_names=["f1", "f2"])
    # intercept first then x1, x2
    assert abs(fit.coef[1] - 0.5) < 0.05
    assert abs(fit.coef[2] - (-0.3)) < 0.05
    assert fit.r2 > 0.9


def test_bh_fdr_basic():
    p = np.array([0.001, 0.002, 0.04, 0.06, 0.5])
    rejected, q = benjamini_hochberg(p, alpha=0.05)
    assert rejected[0] and rejected[1]
    assert not rejected[-1]
    assert (q >= p).any()


def test_consensus_entropy_max_at_uniform():
    uniform = np.full((4, 3), 1 / 3)
    skew = np.array([[0.99, 0.005, 0.005]] * 4)
    assert consensus_entropy(uniform) > consensus_entropy(skew)
