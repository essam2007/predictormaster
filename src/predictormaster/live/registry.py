"""Cross-venue live-game registry. Dedupes Polymarket / Kalshi / sportsbook
markets onto one canonical ``LiveGame`` keyed by (league, start-bucket, team-pair)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from ..markets.kalshi import KalshiMarket
from ..markets.kalshi import midprice as kalshi_midprice
from ..markets.polymarket import PolyMarket
from ..markets.polymarket import is_live as poly_live
from ..markets.sportsbooks import BookOdds


@dataclass(frozen=True)
class MarketRef:
    venue: str
    market_id: str
    implied_home: float
    implied_away: float


@dataclass
class LiveGame:
    game_id: str
    league: str
    home: str
    away: str
    home_entity_id: str
    away_entity_id: str
    start_utc: datetime | None
    venues: dict[str, MarketRef] = field(default_factory=dict)


_NON_ALPHA = re.compile(r"[^a-z0-9]+")
_PAIR = re.compile(
    r"^(?:will\s+)?(?P<a>[^?@]+?)\s+(?:vs\.?|v\.?|@|at|beat|defeat|win against)\s+(?P<b>[^?]+?)\??$",
    re.IGNORECASE,
)
_LEAGUES = {"nba", "nfl", "mlb", "nhl", "soccer", "epl", "ucl", "ufc", "mma", "tennis", "ncaa", "f1", "boxing", "golf"}


def normalise(name: str, aliases: dict[str, str] | None = None) -> str:
    n = _NON_ALPHA.sub("", name.lower())
    if aliases and n in aliases:
        return aliases[n]
    return n


def parse_teams(question: str) -> tuple[str, str] | None:
    if not question:
        return None
    m = _PAIR.match(question.strip())
    if not m:
        return None
    return m.group("a").strip(), m.group("b").strip()


def league_of_tags(tags: tuple[str, ...]) -> str:
    for t in tags:
        if t in _LEAGUES:
            return t
    return "sports"


def _bucket(dt: datetime | None, minutes: int = 30) -> int:
    if dt is None:
        return 0
    return int(dt.timestamp() // (minutes * 60))


def _league_from_kalshi(series: str) -> str:
    s = series.upper()
    for code in ("NBA", "NFL", "MLB", "NHL", "EPL", "UEFA", "NCAA", "TENNIS", "UFC", "BOXING", "F1"):
        if s.endswith(code):
            return code.lower() if code != "UEFA" else "ucl"
    return "sports"


def _league_from_oddsapi(sport: str) -> str:
    s = sport.lower()
    if "basketball_nba" in s:
        return "nba"
    if "americanfootball_nfl" in s:
        return "nfl"
    if "baseball_mlb" in s:
        return "mlb"
    if "icehockey_nhl" in s:
        return "nhl"
    if "soccer" in s:
        return "soccer"
    if "tennis" in s:
        return "tennis"
    return s.split("_")[-1] or "sports"


class LiveRegistry:
    def __init__(self, aliases: dict[str, str] | None = None):
        self.aliases = aliases or {}
        self.games: dict[str, LiveGame] = {}

    def _key(self, league: str, start: datetime | None, a: str, b: str) -> str:
        na = normalise(a, self.aliases)
        nb = normalise(b, self.aliases)
        pair = "-".join(sorted([na, nb]))
        return f"{league}:{_bucket(start)}:{pair}"

    def _ensure(self, league: str, a: str, b: str, start: datetime | None) -> LiveGame:
        key = self._key(league, start, a, b)
        g = self.games.get(key)
        if g is None:
            g = LiveGame(
                game_id=key,
                league=league,
                home=a,
                away=b,
                home_entity_id=normalise(a, self.aliases),
                away_entity_id=normalise(b, self.aliases),
                start_utc=start,
            )
            self.games[key] = g
        return g

    def add_polymarket(self, m: PolyMarket) -> str | None:
        if not poly_live(m):
            return None
        pair = parse_teams(m.question)
        if pair is None:
            return None
        a, b = pair
        league = league_of_tags(m.tags)
        g = self._ensure(league, a, b, m.start_utc)
        h = m.prices[0] if m.prices else 0.0
        aw = m.prices[1] if len(m.prices) > 1 else (1.0 - h if h else 0.0)
        g.venues["polymarket"] = MarketRef("polymarket", m.market_id, float(h), float(aw))
        return g.game_id

    def add_kalshi(self, m: KalshiMarket) -> str | None:
        pair = parse_teams(m.title) or parse_teams(m.subtitle)
        if pair is None:
            return None
        a, b = pair
        league = _league_from_kalshi(m.series_ticker)
        g = self._ensure(league, a, b, m.open_time)
        p = kalshi_midprice(m)
        g.venues["kalshi"] = MarketRef("kalshi", m.ticker, float(p), float(1.0 - p))
        return g.game_id

    def add_sportsbook(self, o: BookOdds) -> str | None:
        league = _league_from_oddsapi(o.sport)
        g = self._ensure(league, o.home, o.away, o.commence_utc)
        g.venues["sportsbooks"] = MarketRef(
            "sportsbooks", o.event_id, float(o.implied_home), float(o.implied_away)
        )
        return g.game_id

    def list(self) -> list[LiveGame]:
        return list(self.games.values())

    def clear(self) -> None:
        self.games.clear()
