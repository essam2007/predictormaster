"""Per-game live sentiment fusion: blend text, narrative, and market signals."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..nlp.sentiment import RollingSentiment
from .market_sentiment import MarketFeatures
from .market_sentiment import features as market_features
from .registry import LiveGame


@dataclass(frozen=True)
class TeamSentiment:
    polarity: float
    intensity: float
    n_messages: int


@dataclass(frozen=True)
class LiveSentiment:
    game_id: str
    league: str
    home: str
    away: str
    start_utc: datetime | None
    home_sent: TeamSentiment
    away_sent: TeamSentiment
    market: MarketFeatures
    composite_home: float
    composite_away: float
    venues: dict[str, dict[str, float]]
    updated_utc: datetime


@dataclass
class FusionConfig:
    w_text: float = 0.4
    w_market: float = 0.4
    w_narrative: float = 0.2


def _team_sent(roll: RollingSentiment, entity_id: str) -> TeamSentiment:
    f = roll.features(entity_id)
    return TeamSentiment(
        polarity=float(f.get("polarity_mean", 0.0)),
        intensity=float(f.get("intensity_mean", 0.0)),
        n_messages=int(f.get("n", 0)),
    )


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def snapshot(g: LiveGame, roll: RollingSentiment, cfg: FusionConfig | None = None) -> LiveSentiment:
    cfg = cfg or FusionConfig()
    h = _team_sent(roll, g.home_entity_id)
    a = _team_sent(roll, g.away_entity_id)
    mf = market_features(g)
    market_home = 2.0 * mf.consensus_home - 1.0 if mf.venues_n else 0.0
    market_away = 2.0 * mf.consensus_away - 1.0 if mf.venues_n else 0.0
    composite_h = _clip(cfg.w_text * h.polarity + cfg.w_market * market_home + cfg.w_narrative * h.intensity)
    composite_a = _clip(cfg.w_text * a.polarity + cfg.w_market * market_away + cfg.w_narrative * a.intensity)
    venues = {
        name: {"implied_home": v.implied_home, "implied_away": v.implied_away}
        for name, v in g.venues.items()
    }
    return LiveSentiment(
        game_id=g.game_id,
        league=g.league,
        home=g.home,
        away=g.away,
        start_utc=g.start_utc,
        home_sent=h,
        away_sent=a,
        market=mf,
        composite_home=composite_h,
        composite_away=composite_a,
        venues=venues,
        updated_utc=datetime.now(timezone.utc),
    )


def to_dict(s: LiveSentiment) -> dict:
    return {
        "game_id": s.game_id,
        "league": s.league,
        "home": s.home,
        "away": s.away,
        "start_utc": s.start_utc.isoformat() if s.start_utc else None,
        "home_sentiment": {"polarity": s.home_sent.polarity, "intensity": s.home_sent.intensity, "n": s.home_sent.n_messages},
        "away_sentiment": {"polarity": s.away_sent.polarity, "intensity": s.away_sent.intensity, "n": s.away_sent.n_messages},
        "market": {
            "consensus_home": s.market.consensus_home,
            "consensus_away": s.market.consensus_away,
            "dispersion": s.market.dispersion,
            "venues_n": s.market.venues_n,
            "skew": s.market.skew,
        },
        "composite": {"home": s.composite_home, "away": s.composite_away},
        "venues": s.venues,
        "updated_utc": s.updated_utc.isoformat(),
    }
