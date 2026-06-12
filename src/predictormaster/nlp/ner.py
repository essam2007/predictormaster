"""Entity disambiguation for sports prediction-market sentiment.

The problem is the canonical NER problem in a sports-betting context:
"Will Manchester United beat City?" must bind to the Polymarket
condition_id for that exact fixture — not to Manchester (the city)
or to a vague brand mention of "United".

This module ships three layers, from cheapest to heaviest:

  1. ``DictionaryNER``  — alias-table O(L) per text. Sub-millisecond,
     no ML. The right default for sports because the universe is
     small (~20 EPL teams + 30 NBA + etc.) and ambiguity is mostly
     lexical (nicknames, abbreviations).

  2. ``ContextualNER``  — score each candidate by token co-occurrence
     with domain-specific anchor words ("vs", "match", "game",
     "spread", "moneyline"). Filters false positives where a brand
     mention is just a logo on a stadium ad.

  3. ``TransformerNER``  — optional spaCy / HF Transformers backend
     for free-text streams where the alias table won't cover novel
     spellings. Lazy-imported; only required for the news/RSS sources.

The output is always a list of ``EntityMention(entity_id, span,
confidence)`` per text — never a single best guess, because a single
message can reference multiple matches.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol

_WORD = re.compile(r"\w+", re.UNICODE)
_SPORTS_ANCHORS = {
    "vs", "v", "vs.", "v.", "at", "@", "match", "game", "matchup",
    "fixture", "spread", "moneyline", "ml", "odds", "line", "favorite",
    "underdog", "win", "beat", "defeat", "kickoff", "tip-off", "playoff",
    "playoffs", "final", "semifinal", "quarterfinal", "elimination",
    "victory", "loss",
}


@dataclass(frozen=True)
class EntityMention:
    entity_id: str          # canonical id used throughout the system
    span: tuple[int, int]   # (start, end) in the original text
    surface: str            # the actual substring matched
    confidence: float       # 0..1
    source: str             # which NER layer found it


class NER(Protocol):
    def extract(self, text: str) -> list[EntityMention]: ...


# ---------------- Dictionary NER ----------------

@dataclass
class DictionaryNER:
    """Build once from a Polymarket / sportsbook universe; reuse forever.

    ``aliases`` maps every known surface form to a canonical entity_id.
    Keys are lower-cased; matching is case-insensitive, whole-token
    only (so "city" matches "Man City" but not "citywide").

    Construction example::

        DictionaryNER.from_universe({
            "team:man_utd": ["Manchester United", "Man Utd", "Man United",
                             "MUFC", "United"],
            "team:man_city": ["Manchester City", "Man City", "MCFC", "City"],
        })

    For ambiguous surface forms ("United" → multiple teams) the
    matcher emits one EntityMention per candidate; downstream
    disambiguation (ContextualNER) resolves the ambiguity.
    """
    aliases: dict[str, set[str]] = field(default_factory=dict)
    """canonical_id → {surface forms (lower-case)}"""

    surface_to_ids: dict[str, list[str]] = field(default_factory=dict)
    """surface (lower-case) → [canonical_id, ...] for collision handling"""

    min_surface_len: int = 2

    @classmethod
    def from_universe(cls, universe: dict[str, list[str]]) -> DictionaryNER:
        n = cls()
        for canon, surfaces in universe.items():
            n.aliases[canon] = set()
            for s in surfaces:
                k = s.lower()
                if len(k) < n.min_surface_len:
                    continue
                n.aliases[canon].add(k)
                n.surface_to_ids.setdefault(k, []).append(canon)
        return n

    def extract(self, text: str) -> list[EntityMention]:
        out: list[EntityMention] = []
        # Walk every token-bounded substring of length up to the max
        # alias length. Cheap because alias lengths are bounded (typical
        # max ~4 tokens for "Borussia Mönchengladbach" etc.).
        tokens = list(_WORD.finditer(text))
        if not tokens:
            return out
        max_span = 4
        for i in range(len(tokens)):
            for j in range(i + 1, min(len(tokens), i + max_span) + 1):
                start = tokens[i].start()
                end = tokens[j - 1].end()
                surface = text[start:end].lower()
                if surface not in self.surface_to_ids:
                    continue
                for canon in self.surface_to_ids[surface]:
                    # Confidence ↓ when the surface is shared across N entities.
                    n_collisions = len(self.surface_to_ids[surface])
                    out.append(EntityMention(
                        entity_id=canon, span=(start, end),
                        surface=text[start:end],
                        confidence=1.0 / n_collisions,
                        source="dictionary",
                    ))
        return _dedupe_overlapping(out)


def _dedupe_overlapping(mentions: list[EntityMention]) -> list[EntityMention]:
    """Keep the longest match at each span position.

    Prevents "Man City" from also matching "Man" and "City" as two
    separate (collision-bearing) entities.
    """
    if not mentions:
        return mentions
    # Sort by start ASC, length DESC.
    mentions_sorted = sorted(
        mentions, key=lambda m: (m.span[0], -(m.span[1] - m.span[0])),
    )
    out: list[EntityMention] = []
    last_end = -1
    for m in mentions_sorted:
        if m.span[0] >= last_end:
            out.append(m)
            last_end = m.span[1]
        elif m.span[0] == out[-1].span[0] and m.span[1] == out[-1].span[1]:
            # Same exact span but different entity_id — alias collision.
            # Keep all candidates so disambiguation can decide.
            out.append(m)
    return out


# ---------------- Contextual disambiguation ----------------

@dataclass
class ContextualNER:
    """Boost confidence of mentions that appear near sports anchor words.

    Wraps a base NER (typically DictionaryNER) and re-weights its
    output. A mention adjacent to "vs", "spread", "match" gets a
    confidence boost; a lone mention in unrelated context gets damped.

    The implementation is intentionally simple — a token-window check —
    rather than a learned discriminator, because: (a) the universe is
    small, (b) we can re-tune the anchor set without retraining,
    (c) Bayesian update with a hand-tuned likelihood is more
    interpretable than a black-box ranker.
    """
    base: NER
    anchors: set[str] = field(default_factory=lambda: set(_SPORTS_ANCHORS))
    window_tokens: int = 6
    boost: float = 0.5
    damp: float = 0.4

    def extract(self, text: str) -> list[EntityMention]:
        candidates = self.base.extract(text)
        if not candidates:
            return candidates
        token_positions = [(m.start(), m.end(), m.group(0).lower())
                           for m in _WORD.finditer(text)]
        out: list[EntityMention] = []
        for c in candidates:
            near = self._anchors_near(c.span, token_positions)
            if near:
                conf = min(1.0, c.confidence + self.boost * (1 - c.confidence))
            else:
                conf = max(0.0, c.confidence * self.damp)
            out.append(EntityMention(
                entity_id=c.entity_id, span=c.span,
                surface=c.surface, confidence=conf,
                source=f"{c.source}+context",
            ))
        return out

    def _anchors_near(self, span: tuple[int, int],
                      tokens: list[tuple[int, int, str]]) -> bool:
        idx_in = -1
        for i, (s, e, _w) in enumerate(tokens):
            if s >= span[0] and e <= span[1]:
                idx_in = i
                break
        if idx_in < 0:
            # Span doesn't align to a single token (multi-word alias).
            # Find the first token whose start ≥ span[0].
            for i, (s, _e, _w) in enumerate(tokens):
                if s >= span[0]:
                    idx_in = i
                    break
            if idx_in < 0:
                return False
        lo = max(0, idx_in - self.window_tokens)
        hi = min(len(tokens), idx_in + self.window_tokens + 1)
        return any(tokens[k][2] in self.anchors for k in range(lo, hi))


# ---------------- Transformer fallback (lazy) ----------------

@dataclass
class TransformerNER:  # pragma: no cover — integration only
    """Optional HuggingFace pipeline NER for novel free-text sources.

    Costs ~50ms/text on CPU. Only used when DictionaryNER's recall is
    too low (typically news streams that introduce names absent from
    our alias table). Maps HF outputs back into the canonical
    entity_id space via a learned alignment dictionary.
    """
    model_name: str = "Davlan/bert-base-multilingual-cased-ner-hrl"
    alignment: dict[str, str] = field(default_factory=dict)
    _pipe = None

    def _ensure(self):
        if self._pipe is None:
            from transformers import pipeline
            self._pipe = pipeline("ner", model=self.model_name,
                                  aggregation_strategy="simple")
        return self._pipe

    def extract(self, text: str) -> list[EntityMention]:
        pipe = self._ensure()
        out: list[EntityMention] = []
        for span in pipe(text):
            surface = span["word"].lower()
            canon = self.alignment.get(surface)
            if canon is None:
                continue
            out.append(EntityMention(
                entity_id=canon,
                span=(int(span["start"]), int(span["end"])),
                surface=span["word"],
                confidence=float(span["score"]),
                source="transformer",
            ))
        return out


# ---------------- Aggregation across layers ----------------

def merge_layers(*layers: list[EntityMention]) -> list[EntityMention]:
    """Combine outputs from multiple NER layers, deduping by entity_id.

    Keeps the highest-confidence mention per entity_id. Useful when
    running dictionary + transformer in parallel and reconciling.
    """
    best: dict[str, EntityMention] = {}
    for layer in layers:
        for m in layer:
            cur = best.get(m.entity_id)
            if cur is None or m.confidence > cur.confidence:
                best[m.entity_id] = m
    return sorted(best.values(), key=lambda m: -m.confidence)


def confidence_threshold(mentions: list[EntityMention],
                         min_conf: float = 0.5) -> list[EntityMention]:
    """Drop low-confidence mentions. Default 0.5 is the boundary above
    which dictionary collisions are typically resolved by context."""
    return [m for m in mentions if m.confidence >= min_conf]


# ---------------- Helpers ----------------

def build_sports_universe(teams_by_league: dict[str, list[tuple[str, list[str]]]]
                          ) -> dict[str, list[str]]:
    """Helper to build a canonical universe from league/team data.

    ``teams_by_league`` example::

        {
            "epl": [
                ("man_utd", ["Manchester United", "Man Utd", "MUFC"]),
                ("man_city", ["Manchester City", "Man City", "MCFC"]),
            ],
            "nba": [...],
        }

    Returns the format expected by ``DictionaryNER.from_universe``.
    """
    universe: dict[str, list[str]] = defaultdict(list)
    for league, teams in teams_by_league.items():
        for entity_id, surfaces in teams:
            canon = f"team:{league}:{entity_id}"
            universe[canon].extend(surfaces)
    return dict(universe)
