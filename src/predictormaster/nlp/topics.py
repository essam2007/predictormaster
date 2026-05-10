"""Dynamic topic modelling and narrative-velocity computation.

Production uses BERTopic with a sentence-transformers backbone over rolling
seasonal windows. This module provides:

* a deterministic TF-IDF + KMeans baseline (no external models required), and
* `narrative_velocity`, the rate of change of topic centroids in embedding
  space across consecutive periods.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np


def tfidf_vectors(docs: list[str]) -> tuple[np.ndarray, list[str]]:
    tokenised = [d.lower().split() for d in docs]
    vocab = sorted({t for d in tokenised for t in d})
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    n = len(docs)
    df = Counter()
    for d in tokenised:
        for w in set(d):
            df[w] += 1
    idf = np.array([np.log((1 + n) / (1 + df[w])) + 1.0 for w in vocab])
    M = np.zeros((n, len(vocab)))
    for i, d in enumerate(tokenised):
        if not d:
            continue
        tf = Counter(d)
        for w, c in tf.items():
            M[i, vocab_idx[w]] = c / len(d)
    M = M * idf[None, :]
    norms = np.linalg.norm(M, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return M / norms, vocab


@dataclass
class KMeansTopics:
    centroids: np.ndarray
    assignments: np.ndarray
    vocab: list[str]


def kmeans_topics(docs: list[str], k: int, *, seed: int = 0, max_iter: int = 50) -> KMeansTopics:
    X, vocab = tfidf_vectors(docs)
    rng = np.random.default_rng(seed)
    if X.shape[0] < k:
        k = max(1, X.shape[0])
    init = rng.choice(X.shape[0], size=k, replace=False)
    C = X[init].copy()
    assign = np.zeros(X.shape[0], dtype=int)
    for _ in range(max_iter):
        d = ((X[:, None, :] - C[None, :, :]) ** 2).sum(axis=2)
        new_assign = np.argmin(d, axis=1)
        if np.array_equal(new_assign, assign):
            break
        assign = new_assign
        for c in range(k):
            mask = assign == c
            if mask.any():
                C[c] = X[mask].mean(axis=0)
    return KMeansTopics(centroids=C, assignments=assign, vocab=vocab)


def narrative_velocity(prev: np.ndarray, curr: np.ndarray) -> float:
    """L2 displacement of the matched-topic centroids per unit time.

    Topics are matched greedily by maximum cosine similarity; the metric is
    the mean of the matched-pair distances.
    """
    if prev.shape != curr.shape:
        m = min(prev.shape[0], curr.shape[0])
        prev = prev[:m]
        curr = curr[:m]
    sim = prev @ curr.T
    matched = np.argmax(sim, axis=1)
    diffs = curr[matched] - prev
    return float(np.linalg.norm(diffs, axis=1).mean())
