"""Sports-domain sentiment classifier.

Production wraps a fine-tuned DeBERTa multi-label head served via
TorchServe. This module ships:

* A `LexiconScorer` baseline that runs without a model and is used as the
  cold-start scorer until the trained head is loaded.
* A clean `SentimentModel` interface so swapping the backend is one line.
* A streaming aggregator that turns a per-message stream into per-entity
  rolling sentiment features.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np


_POS_LEXICON = {"great", "win", "dominant", "stunning", "elite", "improved", "fit", "back"}
_NEG_LEXICON = {"injury", "out", "doubtful", "fatigued", "lost", "poor", "rumour", "suspended"}


class SentimentModel(Protocol):
    def score(self, text: str) -> dict[str, float]: ...


@dataclass
class LexiconScorer:
    pos: set[str] = field(default_factory=lambda: set(_POS_LEXICON))
    neg: set[str] = field(default_factory=lambda: set(_NEG_LEXICON))

    def score(self, text: str) -> dict[str, float]:
        toks = [t.lower() for t in text.split()]
        n_pos = sum(t in self.pos for t in toks)
        n_neg = sum(t in self.neg for t in toks)
        total = max(len(toks), 1)
        polarity = (n_pos - n_neg) / total
        intensity = (n_pos + n_neg) / total
        return {
            "polarity": polarity,
            "intensity": intensity,
            "injury": float("injury" in toks or "out" in toks),
            "lineup": float("lineup" in toks or "starting" in toks),
        }


@dataclass
class TransformerSentiment:  # pragma: no cover - integration
    checkpoint: str = "predictormaster/sports-deberta-v3"
    _pipeline: object | None = None

    def _pipe(self):
        if self._pipeline is None:
            from transformers import pipeline

            self._pipeline = pipeline(
                "text-classification",
                model=self.checkpoint,
                top_k=None,
                truncation=True,
            )
        return self._pipeline

    def score(self, text: str) -> dict[str, float]:
        out = self._pipe()(text)[0]
        return {item["label"]: float(item["score"]) for item in out}


@dataclass
class RollingSentiment:
    window: timedelta = timedelta(minutes=30)
    by_entity: dict[str, deque[tuple[datetime, dict[str, float]]]] = field(
        default_factory=lambda: defaultdict(deque)
    )

    def ingest(self, entity_id: str, ts: datetime, scores: dict[str, float]) -> None:
        q = self.by_entity[entity_id]
        q.append((ts, scores))
        cutoff = ts - self.window
        while q and q[0][0] < cutoff:
            q.popleft()

    def features(self, entity_id: str) -> dict[str, float]:
        q = self.by_entity.get(entity_id) or deque()
        if not q:
            return {"polarity": 0.0, "intensity": 0.0, "n": 0.0}
        keys = q[0][1].keys()
        out = {f"{k}_mean": float(np.mean([s[k] for _, s in q])) for k in keys}
        out["polarity_slope"] = _slope([s["polarity"] for _, s in q])
        out["n"] = float(len(q))
        return out


def _slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.asarray(values)
    return float(np.polyfit(x, y, 1)[0])
