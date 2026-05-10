from __future__ import annotations

import numpy as np

from predictormaster.validation.calibration import (
    brier_decomposition,
    brier_skill_score,
    expected_calibration_error,
    log_loss,
)


def test_brier_decomposition_identity():
    rng = np.random.default_rng(0)
    n = 5000
    p = rng.beta(2, 5, size=n)
    y = rng.binomial(1, p)
    rel, res, unc = brier_decomposition(p, y, n_bins=20)
    bs_direct = float(np.mean((p - y) ** 2))
    # BS = REL - RES + UNC must hold up to small bin-bias.
    assert abs(bs_direct - (rel - res + unc)) < 0.01


def test_ece_small_for_calibrated_forecaster():
    rng = np.random.default_rng(1)
    n = 20000
    p = rng.uniform(0, 1, size=n)
    y = rng.binomial(1, p)  # perfectly calibrated by construction
    rep = expected_calibration_error(p, y, n_bins=15)
    assert rep.ece < 0.02
    assert rep.brier > 0


def test_bss_against_climatology():
    rng = np.random.default_rng(2)
    n = 4000
    p = rng.uniform(0.3, 0.7, size=n)
    y = rng.binomial(1, p)
    bss = brier_skill_score(p, y, baseline_probs=np.full(n, y.mean()))
    assert -1.0 < bss < 1.0


def test_log_loss_monotone_with_better_probs():
    rng = np.random.default_rng(3)
    y = rng.binomial(1, 0.5, size=1000)
    bad = np.full_like(y, 0.5, dtype=float)
    good = np.where(y == 1, 0.9, 0.1).astype(float)
    assert log_loss(good, y) < log_loss(bad, y)
