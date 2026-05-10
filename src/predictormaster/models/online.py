"""Online logistic regression by stochastic gradient (Vowpal-Wabbit-style).

Single-pass updates with adaptive per-feature learning rates (AdaGrad). Used
for between-batch refreshes and for fast-arrival contextual signals
(injuries, narrative shifts) that should propagate to scoring within
seconds.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = np.exp(-z)
        return float(1.0 / (1.0 + ez))
    ez = np.exp(z)
    return float(ez / (1.0 + ez))


@dataclass
class OnlineLogistic:
    lr: float = 0.1
    l2: float = 1e-4
    weights: dict[str, float] = field(default_factory=dict)
    grad_sq: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    bias: float = 0.0
    bias_g: float = 0.0

    def predict(self, x: dict[str, float]) -> float:
        z = self.bias + sum(self.weights.get(k, 0.0) * v for k, v in x.items())
        return _sigmoid(z)

    def update(self, x: dict[str, float], y: int) -> float:
        p = self.predict(x)
        err = p - y
        self.bias_g += err**2
        self.bias -= self.lr * err / (1e-6 + np.sqrt(self.bias_g))
        for k, v in x.items():
            g = err * v + self.l2 * self.weights.get(k, 0.0)
            self.grad_sq[k] += g**2
            self.weights[k] = self.weights.get(k, 0.0) - self.lr * g / (1e-6 + np.sqrt(self.grad_sq[k]))
        return p
