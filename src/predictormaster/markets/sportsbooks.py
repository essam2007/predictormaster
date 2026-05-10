"""The Odds API adapter — book-consensus h2h implied probabilities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..data.ingestion.sources import _get_json

BASE = "https://api.the-odds-api.com/v4"


@dataclass(frozen=True)
class BookOdds:
    event_id: str
    sport: str
    home: str
    away: str
    commence_utc: datetime | None
    implied_home: float
    implied_away: float
    n_books: int


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _decimal_to_implied(price: float) -> float:
    return 1.0 / price if price and price > 1.0 else 0.0


def _to_consensus(r: dict[str, Any]) -> BookOdds | None:
    home = str(r.get("home_team", ""))
    away = str(r.get("away_team", ""))
    hs: list[float] = []
    aws: list[float] = []
    for book in r.get("bookmakers") or []:
        for mkt in book.get("markets") or []:
            if mkt.get("key") != "h2h":
                continue
            for o in mkt.get("outcomes") or []:
                imp = _decimal_to_implied(float(o.get("price", 0) or 0))
                if o.get("name") == home:
                    hs.append(imp)
                elif o.get("name") == away:
                    aws.append(imp)
    if not hs or not aws:
        return None
    return BookOdds(
        event_id=str(r.get("id", "")),
        sport=str(r.get("sport_key", "")),
        home=home,
        away=away,
        commence_utc=_parse_dt(r.get("commence_time")),
        implied_home=sum(hs) / len(hs),
        implied_away=sum(aws) / len(aws),
        n_books=max(len(hs), len(aws)),
    )


def list_live_odds(*, sport: str = "upcoming", api_key: str | None = None) -> list[BookOdds]:
    body = _get_json(
        f"{BASE}/sports/{sport}/odds",
        {
            "regions": "us,uk,eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
            "apiKey": api_key or "",
        },
    )
    rows = body if isinstance(body, list) else (body.get("data") or [])
    out: list[BookOdds] = []
    for r in rows:
        c = _to_consensus(r)
        if c is not None:
            out.append(c)
    return out
