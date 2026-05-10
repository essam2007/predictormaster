"""Tests for multi-class calibration metrics."""
from __future__ import annotations

import numpy as np

from predictormaster.validation.calibration import (
    brier_multiclass,
    class_wise_ece,
    expected_calibration_error,
    top_label_ece,
)


def test_top_label_ece_calibrated_is_small():
    rng = np.random.default_rng(0)
    n = 5000
    K = 3
    p_top = rng.uniform(0.3, 0.95, size=n)
    rest = (1 - p_top) / (K - 1)
    probs = np.column_stack([p_top, rest, rest])
    correct = rng.binomial(1, p_top)
    labels = np.where(correct == 1, 0, rng.integers(1, K, size=n))
    ece = top_label_ece(probs, labels, n_bins=15)
    assert ece < 0.04


def test_class_wise_ece_returns_dict_per_class():
    rng = np.random.default_rng(1)
    n = 2000
    K = 4
    raw = rng.dirichlet(np.ones(K), size=n)
    labels = np.array([rng.choice(K, p=row) for row in raw])
    ecew = class_wise_ece(raw, labels, n_bins=10)
    assert set(ecew.keys()) == set(range(K))
    for v in ecew.values():
        assert 0.0 <= v <= 1.0


def test_brier_multiclass_reduces_to_2x_binary_when_K2():
    rng = np.random.default_rng(2)
    n = 1000
    p_pos = rng.uniform(0, 1, size=n)
    y = rng.binomial(1, p_pos)
    binary_brier = float(np.mean((p_pos - y) ** 2))
    probs2d = np.column_stack([1 - p_pos, p_pos])
    bm = brier_multiclass(probs2d, y)
    # multi-class: sum_k (p_k - 1{y=k})^2 = (p_neg)^2 + (p_pos - y)^2 when y=1
    # which equals 2 * binary_brier in expectation up to bias.
    assert abs(bm - 2 * binary_brier) < 1e-9


def test_top_label_ece_consistent_with_binary_when_K2():
    rng = np.random.default_rng(3)
    n = 4000
    p_pos = rng.uniform(0, 1, size=n)
    y = rng.binomial(1, p_pos)
    ece_binary = expected_calibration_error(p_pos, y, n_bins=15).ece
    probs2d = np.column_stack([1 - p_pos, p_pos])
    ece_top = top_label_ece(probs2d, y, n_bins=15)
    # They differ in convention (top-label ECE bins on confidence, binary
    # bins on raw p_pos) but on a perfectly-calibrated stream both should
    # be small.
    assert ece_binary < 0.03
    assert ece_top < 0.05
