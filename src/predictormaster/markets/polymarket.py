"""Polymarket Gamma + CLOB read-only clients.

HTTP is dispatched via ``data.ingestion.sources._get_json`` so a single
``set_http`` shim covers every adapter in tests.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..data.ingestion.sources import _get_json

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

SPORT_TAGS = {
    "sports", "nba", "nfl", "mlb", "nhl", "soccer", "epl", "ucl",
    "ufc", "mma", "tennis", "f1", "ncaa", "boxing", "golf",
}


@dataclass(frozen=True)
class PolyMarket:
    market_id: str
    question: str
    slug: str
    tags: tuple[str, ...]
    start_utc: datetime | None
    end_utc: datetime | None
    active: bool
    closed: bool
    accepting_orders: bool
    outcomes: tuple[str, ...]
    token_ids: tuple[str, ...]
    prices: tuple[float, ...]


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coerce_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _to_market(row: dict[str, Any]) -> PolyMarket:
    tags_raw = row.get("tags") or row.get("category") or []
    if isinstance(tags_raw, str):
        tags_raw = [tags_raw]
    tags = tuple(str(t).lower() for t in tags_raw)
    return PolyMarket(
        market_id=str(row.get("id") or row.get("conditionId") or ""),
        question=str(row.get("question", "")),
        slug=str(row.get("slug", "")),
        tags=tags,
        start_utc=_parse_dt(row.get("startDate")),
        end_utc=_parse_dt(row.get("endDate")),
        active=bool(row.get("active", False)),
        closed=bool(row.get("closed", False)),
        accepting_orders=bool(row.get("acceptingOrders", row.get("enableOrderBook", False))),
        outcomes=tuple(str(o) for o in _coerce_list(row.get("outcomes"))),
        token_ids=tuple(str(t) for t in _coerce_list(row.get("clobTokenIds"))),
        prices=tuple(float(p) for p in _coerce_list(row.get("outcomePrices")) if _is_number(p)),
    )


def _is_number(p: Any) -> bool:
    try:
        float(p)
        return True
    except (TypeError, ValueError):
        return False


def list_sports_markets(*, limit: int = 200, offset: int = 0) -> list[PolyMarket]:
    body = _get_json(
        f"{GAMMA}/markets",
        {
            "limit": limit,
            "offset": offset,
            "active": "true",
            "closed": "false",
            "order": "volume",
            "ascending": "false",
        },
    )
    items = body if isinstance(body, list) else (body.get("data") or body.get("markets") or [])
    out: list[PolyMarket] = []
    for r in items:
        m = _to_market(r)
        if SPORT_TAGS.intersection(m.tags) or "sports" in m.slug.lower():
            out.append(m)
    return out


def is_live(m: PolyMarket, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not m.active or m.closed or not m.accepting_orders:
        return False
    if m.start_utc and m.start_utc > now:
        return False
    return not (m.end_utc and m.end_utc < now)


def midprice(token_id: str) -> float | None:
    body = _get_json(f"{CLOB}/midpoint", {"token_id": token_id})
    val = body.get("mid") if isinstance(body, dict) else None
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def midprices(token_ids: Iterable[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for tid in token_ids:
        m = midprice(tid)
        if m is not None:
            out[tid] = m
    return out
