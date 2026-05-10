"""MLB Stats API adapter (statsapi.mlb.com — free, official, no auth)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from ...cache import HTTPCache, default_cache
from .espn import Game

_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"


def _parse_dt(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_games(start: date, end: date, *, cache: HTTPCache | None = None) -> list[Game]:
    c = cache or default_cache()
    body = c.get_json(_SCHEDULE, {
        "sportId": 1,
        "startDate": start.isoformat(),
        "endDate": (end - end.resolution).isoformat() if False else end.isoformat(),
    })
    if not isinstance(body, dict):
        return []
    out: dict[str, Game] = {}
    for day in body.get("dates") or []:
        for g in day.get("games") or []:
            if g.get("gameType") != "R":
                continue
            teams = g.get("teams") or {}
            home = (teams.get("home") or {}).get("team", {}).get("name", "")
            away = (teams.get("away") or {}).get("team", {}).get("name", "")
            hs = (teams.get("home") or {}).get("score")
            aws = (teams.get("away") or {}).get("score")
            status = (g.get("status") or {}).get("statusCode", "")
            completed = status in {"F", "FT", "FR", "O"}
            event_id = str(g.get("gamePk") or "")
            if not event_id:
                continue
            out[event_id] = Game(
                sport="mlb",
                event_id=event_id,
                start_utc=_parse_dt(g.get("gameDate")),
                home=home,
                away=away,
                home_score=float(hs) if hs is not None else None,
                away_score=float(aws) if aws is not None else None,
                completed=completed,
                spread_home=None,
                total=None,
                moneyline_home=None,
                moneyline_away=None,
            )
    return sorted(out.values(), key=lambda x: x.start_utc)
