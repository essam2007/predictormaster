"""Reinforcement learning agent for adaptive lineup / scenario simulation.

We expose a Gymnasium-style environment interface and a PPO trainer that
delegates to stable-baselines3 in production. A tabular Q-learning fallback
is provided for local experiments and tests on a discretised state-space.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class TabularQ:
    n_actions: int
    alpha: float = 0.1
    gamma: float = 0.95
    epsilon: float = 0.1
    Q: dict[tuple, np.ndarray] = field(default_factory=dict)

    def _q(self, state: tuple) -> np.ndarray:
        if state not in self.Q:
            self.Q[state] = np.zeros(self.n_actions)
        return self.Q[state]

    def act(self, state: tuple, *, rng: np.random.Generator) -> int:
        if rng.random() < self.epsilon:
            return int(rng.integers(self.n_actions))
        return int(np.argmax(self._q(state)))

    def update(self, s: tuple, a: int, r: float, sp: tuple, done: bool) -> None:
        target = r + (0.0 if done else self.gamma * float(np.max(self._q(sp))))
        self._q(s)[a] += self.alpha * (target - self._q(s)[a])


def train_tabular(env, agent: TabularQ, *, episodes: int, seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    returns: list[float] = []
    for _ in range(episodes):
        s, _ = env.reset()
        done = False
        total = 0.0
        while not done:
            a = agent.act(s, rng=rng)
            sp, r, terminated, truncated, _ = env.step(a)
            done = terminated or truncated
            agent.update(s, a, r, sp, done)
            s = sp
            total += r
        returns.append(total)
    return returns
