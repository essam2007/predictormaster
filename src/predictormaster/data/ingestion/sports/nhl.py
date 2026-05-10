"""NHL public schedule adapter (api-web.nhle.com — free, official, no auth)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ...cache import HTTPCache, default_cache
from .espn import Game

_SCHEDULE = "https://api-web.nhle.com/v1/schedule"


def _parse_dt(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_games(start: date, end: date, *, cache: HTTPCache | None = None) -> list[Game]:
    """The endpoint returns a week of games from the given date."""
    c = cache or default_cache()
    out: dict[str, Game] = {}
    d = start
    while d < end:
        body = c.get_json(f"{_SCHEDULE}/{d.isoformat()}")
        d += timedelta(days=7)
        if not isinstance(body, dict):
            continue
        for week in body.get("gameWeek") or []:
            for g in week.get("games") or []:
                if g.get("gameType") != 2:
                    continue
                event_id = str(g.get("id") or "")
                if not event_id or event_id in out:
                    continue
                home = (g.get("homeTeam") or {}).get("placeName", {}).get("default", "") + " " + (g.get("homeTeam") or {}).get("name", {}).get("default", "")
                away = (g.get("awayTeam") or {}).get("placeName", {}).get("default", "") + " " + (g.get("awayTeam") or {}).get("name", {}).get("default", "")
                hs = (g.get("homeTeam") or {}).get("score")
                aws = (g.get("awayTeam") or {}).get("score")
                state = g.get("gameState", "")
                completed = state in {"OFF", "FINAL"}
                out[event_id] = Game(
                    sport="nhl",
                    event_id=event_id,
                    start_utc=_parse_dt(g.get("startTimeUTC")),
                    home=home.strip(),
                    away=away.strip(),
                    home_score=float(hs) if hs is not None else None,
                    away_score=float(aws) if aws is not None else None,
                    completed=completed,
                    spread_home=None,
                    total=None,
                    moneyline_home=None,
                    moneyline_away=None,
                )
    return sorted(out.values(), key=lambda x: x.start_utc)
