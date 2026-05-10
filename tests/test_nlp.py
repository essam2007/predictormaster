from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from predictormaster.nlp.contagion import simulate_contagion
from predictormaster.nlp.sentiment import LexiconScorer, RollingSentiment
from predictormaster.nlp.topics import kmeans_topics, narrative_velocity, tfidf_vectors


def test_lexicon_polarity_signs():
    s = LexiconScorer()
    assert s.score("great win improved")["polarity"] > 0
    assert s.score("injury out poor")["polarity"] < 0


def test_rolling_window_drops_old():
    s = RollingSentiment(window=timedelta(seconds=10))
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    s.ingest("p1", base, {"polarity": 0.1, "intensity": 0.2})
    s.ingest("p1", base + timedelta(seconds=20), {"polarity": 0.5, "intensity": 0.3})
    f = s.features("p1")
    # The earlier observation should have been dropped.
    assert f["n"] == 1
    assert abs(f["polarity_mean"] - 0.5) < 1e-6


def test_kmeans_topics_runs():
    docs = ["injury news bad", "great win victory", "lineup change rumour", "win great form"]
    res = kmeans_topics(docs, k=2, seed=0)
    assert res.assignments.shape == (4,)


def test_narrative_velocity_zero_when_identical():
    X, _ = tfidf_vectors(["a b c", "d e f", "g h i"])
    assert narrative_velocity(X, X) < 1e-9


def test_contagion_decays_to_baseline():
    A = np.ones((5, 5)) - np.eye(5)
    s0 = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
    res = simulate_contagion(adjacency=A, initial_state=s0, beta=0.1, gamma=0.5, steps=50)
    # With strong decay the system should approach zero
    assert np.abs(res.final).max() < 0.5
