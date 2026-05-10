"""ESPN public scoreboard adapter.

Endpoints (no auth, public CDN):
  NFL:    site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  NBA:    site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
  NCAAF:  site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard
  NCAAB:  site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard

Each accepts ``?dates=YYYYMMDD`` for a single day or ``?dates=YYYYMMDD-YYYYMMDD``
for a range. Returns a list of completed and scheduled games with score,
status, and (when available) the closing Vegas line under ``odds``.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from ...cache import HTTPCache, default_cache

_BASE = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
    "ncaab": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
}


@dataclass(frozen=True)
class Game:
    sport: str
    event_id: str
    start_utc: datetime
    home: str
    away: str
    home_score: float | None
    away_score: float | None
    completed: bool
    spread_home: float | None
    total: float | None
    moneyline_home: float | None
    moneyline_away: float | None


def _parse_dt(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _parse_odds(odds_block: list | None, home_name: str) -> tuple[float | None, float | None, float | None, float | None]:
    if not odds_block:
        return None, None, None, None
    o = odds_block[0]
    spread = o.get("spread")
    total = o.get("overUnder")
    home_ml = (o.get("homeTeamOdds") or {}).get("moneyLine")
    away_ml = (o.get("awayTeamOdds") or {}).get("moneyLine")
    spread_home: float | None = None
    if spread is not None:
        details = (o.get("details") or "").split()
        if details and details[0] != home_name and not details[0].isdigit():
            spread_home = -float(spread)
        else:
            spread_home = float(spread)
    return (
        spread_home,
        float(total) if total is not None else None,
        float(home_ml) if home_ml is not None else None,
        float(away_ml) if away_ml is not None else None,
    )


def _parse_event(sport: str, ev: dict) -> Game | None:
    comps = ev.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    competitors = comp.get("competitors") or []
    if len(competitors) != 2:
        return None
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    status = ((comp.get("status") or {}).get("type") or {})
    completed = bool(status.get("completed"))
    hs = home.get("score")
    aws = away.get("score")
    home_name = (home.get("team") or {}).get("displayName") or (home.get("team") or {}).get("name") or ""
    away_name = (away.get("team") or {}).get("displayName") or (away.get("team") or {}).get("name") or ""
    spread_h, total, ml_h, ml_a = _parse_odds(comp.get("odds"), home_name)
    return Game(
        sport=sport,
        event_id=str(ev.get("id", "")),
        start_utc=_parse_dt(ev.get("date")),
        home=home_name,
        away=away_name,
        home_score=float(hs) if hs not in (None, "") else None,
        away_score=float(aws) if aws not in (None, "") else None,
        completed=completed,
        spread_home=spread_h,
        total=total,
        moneyline_home=ml_h,
        moneyline_away=ml_a,
    )


def _daterange(start: date, end: date) -> Iterable[date]:
    d = start
    while d < end:
        yield d
        d += timedelta(days=1)


def fetch_games(sport: str, start: date, end: date, *, cache: HTTPCache | None = None) -> list[Game]:
    if sport not in _BASE:
        raise ValueError(f"ESPN adapter does not cover sport={sport!r}")
    c = cache or default_cache()
    seen: dict[str, Game] = {}
    for d in _daterange(start, end):
        body = c.get_json(_BASE[sport], {"dates": d.strftime("%Y%m%d"), "limit": 300})
        if not isinstance(body, dict):
            continue
        for ev in body.get("events") or []:
            g = _parse_event(sport, ev)
            if g and g.event_id and g.event_id not in seen:
                seen[g.event_id] = g
    return sorted(seen.values(), key=lambda g: g.start_utc)
