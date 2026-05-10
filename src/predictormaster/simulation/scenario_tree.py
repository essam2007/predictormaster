"""Branching scenario simulator conditioned on key in-game events.

Each node represents a (state, time) pair; children are reached by
sampling from the conditional event-distribution at that node. The tree is
expanded breadth-first up to a configurable depth, and the leaves are
returned with their accumulated log-probabilities.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    state: Any
    log_prob: float
    depth: int
    history: list[Any] = field(default_factory=list)


def expand_scenarios(
    *,
    root_state: Any,
    branches: Callable[[Any], list[tuple[Any, float]]],
    max_depth: int,
    log_prob_threshold: float = -8.0,
) -> list[Node]:
    """`branches(state)` returns [(child_state, log_p_child)]."""
    leaves: list[Node] = []
    queue: deque[Node] = deque([Node(state=root_state, log_prob=0.0, depth=0)])
    while queue:
        node = queue.popleft()
        if node.depth == max_depth:
            leaves.append(node)
            continue
        children = branches(node.state)
        if not children:
            leaves.append(node)
            continue
        for child_state, lp in children:
            new_log = node.log_prob + lp
            if new_log < log_prob_threshold:
                continue
            queue.append(
                Node(
                    state=child_state,
                    log_prob=new_log,
                    depth=node.depth + 1,
                    history=node.history + [child_state],
                )
            )
    return leaves
