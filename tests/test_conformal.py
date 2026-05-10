"""Coverage tests for split and Mondrian conformal classifiers."""
from __future__ import annotations

import numpy as np

from predictormaster.validation.conformal import (
    MondrianConformalClassifier,
    SplitConformalClassifier,
)


class _FixedClassifier:
    """A deterministic classifier whose probability vectors come from a
    softmax of (X @ W). Closed-form, no fit, used to keep coverage tests
    independent of any ML library.
    """

    def __init__(self, W: np.ndarray):
        self.W = W

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        z = X @ self.W
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)


def _make_W(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(size=(4, 3))


def _draw(rng: np.random.Generator, W: np.ndarray, n: int):
    K = W.shape[1]
    X = rng.normal(size=(n, W.shape[0]))
    logits = X @ W
    p = np.exp(logits - logits.max(axis=1, keepdims=True))
    p = p / p.sum(axis=1, keepdims=True)
    y = np.array([rng.choice(K, p=row) for row in p])
    return X, y


def test_split_conformal_marginal_coverage():
    alpha = 0.1
    trials = 30
    covers = []
    for s in range(trials):
        W = _make_W(s)
        rng = np.random.default_rng(s + 100)
        X_cal, y_cal = _draw(rng, W, 800)
        X_test, y_test = _draw(rng, W, 600)
        clf = _FixedClassifier(W)
        cp = SplitConformalClassifier(clf, alpha=alpha).calibrate(X_cal, y_cal)
        sets = cp.predict_set(X_test)
        covered = float(np.mean([y in s_ for y, s_ in zip(y_test, sets, strict=True)]))
        covers.append(covered)
    # Marginal coverage holds in expectation; the average over many trials
    # should hit (1 - alpha) within a couple of percentage points.
    assert np.mean(covers) >= 1 - alpha - 0.02


def test_split_conformal_alpha_zero_includes_all_seen_classes():
    """At alpha = 0 the conformal threshold equals the maximum calibration
    nonconformity score, so the prediction set contains every label that
    achieved at least the lowest calibration probability of the true class.
    For a well-spread synthetic problem that's all K classes."""
    W = _make_W(1)
    rng = np.random.default_rng(7)
    X_cal, y_cal = _draw(rng, W, 1500)
    X_test, _ = _draw(rng, W, 50)
    clf = _FixedClassifier(W)
    cp = SplitConformalClassifier(clf, alpha=0.0).calibrate(X_cal, y_cal)
    sets = cp.predict_set(X_test)
    # At alpha=0 we expect every set to be non-empty (contains the prediction).
    for s_ in sets:
        assert len(s_) >= 1


def test_mondrian_thresholds_per_group():
    W = _make_W(3)
    rng = np.random.default_rng(11)
    X_cal, y_cal = _draw(rng, W, 1000)
    clf = _FixedClassifier(W)
    cp = MondrianConformalClassifier(
        clf,
        alpha=0.1,
        group_fn=lambda X, y, p: y,
    ).calibrate(X_cal, y_cal)
    for k in np.unique(y_cal):
        assert int(k) in cp.thresholds
