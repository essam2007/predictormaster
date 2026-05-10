"""football-data.co.uk historical EPL CSVs.

URL convention: https://www.football-data.co.uk/mmz4281/{SS}/{LEAGUE}.csv
where SS is the two-digit start year + two-digit end year (e.g. ``2425`` =
2024-25 season) and LEAGUE is ``E0`` for the Premier League.

Each season CSV ships with full match results plus closing odds from
multiple books (B365H/D/A is Bet365 closing moneyline). We average books
where available to produce a consensus closing line.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone

from ...cache import HTTPCache, default_cache
from .espn import Game

_URL = "https://www.football-data.co.uk/mmz4281/{ss}/E0.csv"

_BOOKS = ("B365", "BW", "IW", "PS", "WH", "VC")


def _season_codes(start: date, end: date) -> list[str]:
    """EPL season runs Aug-May. Map a date range to the season codes it spans."""
    codes: list[str] = []
    y = start.year if start.month >= 8 else start.year - 1
    final_y = end.year if end.month >= 8 else end.year - 1
    while y <= final_y:
        codes.append(f"{y % 100:02d}{(y + 1) % 100:02d}")
        y += 1
    return codes


def _parse_date(s: str) -> datetime:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"unrecognised football-data date {s!r}")


def _avg(values: list[float]) -> float | None:
    vs = [v for v in values if v and v > 1.0]
    if not vs:
        return None
    return sum(vs) / len(vs)


def fetch_games(start: date, end: date, *, cache: HTTPCache | None = None) -> list[Game]:
    c = cache or default_cache()
    games: list[Game] = []
    for code in _season_codes(start, end):
        try:
            text = c.get_text(_URL.format(ss=code))
        except Exception:
            continue
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            if not row.get("Date"):
                continue
            try:
                d = _parse_date(row["Date"])
            except ValueError:
                continue
            if not (start <= d.date() < end):
                continue
            home = row.get("HomeTeam", "")
            away = row.get("AwayTeam", "")
            hg = row.get("FTHG")
            ag = row.get("FTAG")
            home_odds = _avg([float(row[f"{b}H"]) for b in _BOOKS if row.get(f"{b}H")])
            away_odds = _avg([float(row[f"{b}A"]) for b in _BOOKS if row.get(f"{b}A")])
            games.append(Game(
                sport="epl",
                event_id=f"{code}-{home}-{away}-{d.date().isoformat()}",
                start_utc=d,
                home=home,
                away=away,
                home_score=float(hg) if hg not in (None, "") else None,
                away_score=float(ag) if ag not in (None, "") else None,
                completed=hg not in (None, ""),
                spread_home=None,
                total=None,
                moneyline_home=home_odds,
                moneyline_away=away_odds,
            ))
    return sorted(games, key=lambda g: g.start_utc)
