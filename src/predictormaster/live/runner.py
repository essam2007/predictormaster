"""Synchronous tick runner. The async wrapper is deferred — the sync core
is what's tested and what the FastAPI service ticks on a background thread.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..markets import kalshi as kl
from ..markets import polymarket as pm
from ..markets import sportsbooks as sb
from ..nlp.sentiment import LexiconScorer, RollingSentiment
from .fusion import FusionConfig, snapshot
from .registry import LiveRegistry
from .store import SnapshotStore, store
from .text_sources import TextMessage, queries_from


@dataclass
class RunnerConfig:
    odds_sport: str = "upcoming"
    odds_api_key: str | None = None
    fusion: FusionConfig = field(default_factory=FusionConfig)


class Runner:
    def __init__(
        self,
        cfg: RunnerConfig | None = None,
        aliases: dict[str, str] | None = None,
        snap_store: SnapshotStore | None = None,
    ):
        self.cfg = cfg or RunnerConfig()
        self.registry = LiveRegistry(aliases=aliases)
        self.scorer = LexiconScorer()
        self.roll = RollingSentiment()
        self.store = snap_store or store()

    def discover(self) -> None:
        for m in pm.list_sports_markets():
            self.registry.add_polymarket(m)
        for m in kl.list_open_sports_markets():
            self.registry.add_kalshi(m)
        for o in sb.list_live_odds(sport=self.cfg.odds_sport, api_key=self.cfg.odds_api_key):
            self.registry.add_sportsbook(o)

    def ingest_text(self, msgs: Iterable[TextMessage]) -> None:
        for msg in msgs:
            scores = self.scorer.score(msg.text)
            self.roll.ingest(msg.entity_id, msg.ts, scores)

    def fuse(self) -> None:
        for g in self.registry.list():
            self.store.put(snapshot(g, self.roll, self.cfg.fusion))

    def queries(self) -> dict[str, list[str]]:
        return queries_from(self.registry.list())

    def tick(self, msgs: Iterable[TextMessage] = ()) -> None:
        self.discover()
        self.ingest_text(msgs)
        self.fuse()
