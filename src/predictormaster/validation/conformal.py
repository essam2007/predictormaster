"""Split-conformal and Mondrian-conformal classifiers.

Both deliver distribution-free finite-sample coverage guarantees on top of any
``predict_proba``-style classifier.

Split conformal (marginal):
    For target miscoverage level alpha and a held-out calibration set, the
    prediction set ``C(X)`` satisfies
        P[ Y in C(X) ] >= 1 - alpha
    over the joint test/calibration distribution, by exchangeability.

Mondrian conformal (group-conditional):
    Calibration thresholds are computed *per group* (Vovk et al.). Grouping
    by the **true** class on the calibration set delivers finite-sample
    class-conditional coverage:
        P[ Y in C(X) | Y = k ] >= 1 - alpha   for every class k.
    Grouping by the **predicted** class gives only asymptotic class-
    conditional coverage; this implementation supports both and the docstring
    of ``MondrianConformalClassifier`` makes the trade-off explicit.

This module depends only on numpy + the base classifier's ``predict_proba``.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np


def _nonconformity(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    """1 - p_y (the standard score for classification conformal)."""
    n = probs.shape[0]
    return 1.0 - probs[np.arange(n), y]


def _quantile(scores: np.ndarray, alpha: float) -> float:
    """Conformal-corrected (n+1)/n quantile."""
    n = len(scores)
    if n == 0:
        return 1.0
    q = np.ceil((n + 1) * (1 - alpha)) / n
    q = float(min(max(q, 0.0), 1.0))
    return float(np.quantile(scores, q, method="higher"))


@dataclass
class SplitConformalClassifier:
    """Marginal-coverage split conformal wrapper around a fitted base
    classifier exposing ``predict_proba``.

    Usage:
        cp = SplitConformalClassifier(base_clf, alpha=0.1)
        cp.calibrate(X_cal, y_cal)
        sets = cp.predict_set(X_test)         # list[set[int]]
    """

    base: object
    alpha: float = 0.1
    _threshold: float = 1.0

    def calibrate(self, X_cal: np.ndarray, y_cal: np.ndarray) -> "SplitConformalClassifier":
        probs = np.asarray(self.base.predict_proba(X_cal), dtype=float)  # type: ignore[attr-defined]
        scores = _nonconformity(probs, np.asarray(y_cal, dtype=int))
        self._threshold = _quantile(scores, self.alpha)
        return self

    def predict_set(self, X: np.ndarray) -> list[set[int]]:
        probs = np.asarray(self.base.predict_proba(X), dtype=float)  # type: ignore[attr-defined]
        scores = 1.0 - probs  # nonconformity for each candidate label
        keep = scores <= self._threshold
        return [set(np.flatnonzero(row).tolist()) for row in keep]

    @property
    def threshold(self) -> float:
        return self._threshold


@dataclass
class MondrianConformalClassifier:
    """Group-conditional conformal classifier.

    Provide ``group_fn`` mapping each calibration row to a group label. Two
    standard choices:

      * ``group_fn=lambda X, y, p: y``       — group by *true* class on
        calibration. Finite-sample class-conditional coverage holds.
      * ``group_fn=lambda X, y, p: p.argmax(axis=1)`` — group by *predicted*
        class. Class-conditional coverage holds asymptotically only.

    At test time, ``predict_set`` groups each test row by
    ``group_fn_test(X, p)`` (defaults to predicted class) and applies the
    matching per-group threshold.
    """

    base: object
    alpha: float = 0.1
    group_fn: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray] = field(
        default=lambda X, y, p: y
    )
    group_fn_test: Callable[[np.ndarray, np.ndarray], np.ndarray] = field(
        default=lambda X, p: p.argmax(axis=1)
    )
    _thresholds: dict[int, float] = field(default_factory=dict)
    _global_threshold: float = 1.0

    def calibrate(self, X_cal: np.ndarray, y_cal: np.ndarray) -> "MondrianConformalClassifier":
        probs = np.asarray(self.base.predict_proba(X_cal), dtype=float)  # type: ignore[attr-defined]
        y = np.asarray(y_cal, dtype=int)
        scores = _nonconformity(probs, y)
        groups = np.asarray(self.group_fn(X_cal, y, probs))
        for g in np.unique(groups):
            self._thresholds[int(g)] = _quantile(scores[groups == g], self.alpha)
        self._global_threshold = _quantile(scores, self.alpha)
        return self

    def predict_set(self, X: np.ndarray) -> list[set[int]]:
        probs = np.asarray(self.base.predict_proba(X), dtype=float)  # type: ignore[attr-defined]
        groups = np.asarray(self.group_fn_test(X, probs))
        out: list[set[int]] = []
        cand_scores = 1.0 - probs
        for i, g in enumerate(groups):
            thr = self._thresholds.get(int(g), self._global_threshold)
            out.append(set(np.flatnonzero(cand_scores[i] <= thr).tolist()))
        return out

    @property
    def thresholds(self) -> dict[int, float]:
        return dict(self._thresholds)
