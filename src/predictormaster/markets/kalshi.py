"""Kalshi public markets read-only adapter."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..data.ingestion.sources import _get_json

BASE = "https://api.elections.kalshi.com/trade-api/v2"

SPORTS_SERIES = (
    "KXNBA", "KXNFL", "KXMLB", "KXNHL",
    "KXEPL", "KXUEFA", "KXNCAA",
    "KXTENNIS", "KXUFC", "KXBOXING", "KXF1",
)


@dataclass(frozen=True)
class KalshiMarket:
    ticker: str
    series_ticker: str
    title: str
    subtitle: str
    yes_bid: float
    yes_ask: float
    last_price: float
    status: str
    open_time: datetime | None
    close_time: datetime | None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _series_of(r: dict[str, Any]) -> str:
    if "series_ticker" in r and r["series_ticker"]:
        return str(r["series_ticker"])
    et = r.get("event_ticker", "")
    return et.split("-")[0] if et else ""


def _to_market(r: dict[str, Any]) -> KalshiMarket:
    return KalshiMarket(
        ticker=str(r.get("ticker", "")),
        series_ticker=_series_of(r),
        title=str(r.get("title", "")),
        subtitle=str(r.get("subtitle", "") or r.get("yes_sub_title", "")),
        yes_bid=float(r.get("yes_bid", 0) or 0) / 100.0,
        yes_ask=float(r.get("yes_ask", 0) or 0) / 100.0,
        last_price=float(r.get("last_price", 0) or 0) / 100.0,
        status=str(r.get("status", "")),
        open_time=_parse_dt(r.get("open_time")),
        close_time=_parse_dt(r.get("close_time")),
    )


def list_open_sports_markets(*, limit: int = 200) -> list[KalshiMarket]:
    out: list[KalshiMarket] = []
    for series in SPORTS_SERIES:
        body = _get_json(
            f"{BASE}/markets",
            {"status": "open", "series_ticker": series, "limit": limit},
        )
        for r in (body.get("markets") if isinstance(body, dict) else None) or []:
            out.append(_to_market(r))
    return out


def midprice(m: KalshiMarket) -> float:
    if m.yes_bid <= 0 and m.yes_ask <= 0:
        return m.last_price
    if m.yes_bid <= 0:
        return m.yes_ask
    if m.yes_ask <= 0:
        return m.yes_bid
    return (m.yes_bid + m.yes_ask) / 2.0
