"""Stacked-generalisation meta-learner.

Inputs are out-of-fold predictions from the base learners; the meta-model is
multinomial logistic regression with elastic-net regularisation. We do not
fall back to in-sample predictions: the trainer hard-fails if any OOF column
is missing.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import softmax


@dataclass
class StackingMeta:
    coef: np.ndarray  # K x (D+1)  (last column is bias)
    base_learners: list[str]
    classes: list[str]


def _grad_elasticnet(W: np.ndarray, X: np.ndarray, y: np.ndarray, l1: float, l2: float) -> np.ndarray:
    """Subgradient of multinomial logistic loss + elastic net."""
    n = X.shape[0]
    Z = X @ W.T
    P = softmax(Z, axis=1)
    Y = np.eye(W.shape[0])[y]
    grad = (P - Y).T @ X / n
    grad += l2 * W
    grad += l1 * np.sign(W)
    return grad


def fit_stacking(
    *, oof_preds: np.ndarray, y: np.ndarray, base_learners: list[str], classes: list[str],
    l1: float = 1e-3, l2: float = 1e-3, lr: float = 0.5, n_iter: int = 500,
) -> StackingMeta:
    n = len(y)
    X = np.hstack([oof_preds, np.ones((n, 1))])
    K = len(classes)
    W = np.zeros((K, X.shape[1]))
    for _ in range(n_iter):
        g = _grad_elasticnet(W, X, y, l1, l2)
        W = W - lr * g
    return StackingMeta(coef=W, base_learners=base_learners, classes=classes)


def predict_stacking(meta: StackingMeta, base_preds: np.ndarray) -> np.ndarray:
    n = base_preds.shape[0]
    X = np.hstack([base_preds, np.ones((n, 1))])
    return softmax(X @ meta.coef.T, axis=1)
